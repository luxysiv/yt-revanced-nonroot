import os
import re
import json
import logging
import requests
import subprocess
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.support import expected_conditions as EC

# Environment variables for GitHub token and repository
github_token = os.getenv('GITHUB_TOKEN')
repository = os.getenv('GITHUB_REPOSITORY')

# Setup logging
class ColoredLevelFormatter(logging.Formatter):
    COLOR_CODE = {
        'DEBUG':    "\x1b[34m",  # Blue
        'INFO':     "\x1b[32m",  # Green
        'WARNING':  "\x1b[33m",  # Yellow
        'ERROR':    "\x1b[31m",  # Red
        'CRITICAL': "\x1b[41m",  # Red background
    }
    
    TIMESTAMP_COLOR = "\x1b[36m"  # Cyan for timestamp
    RESET_COLOR = "\x1b[0m"       # Reset color

    def format(self, record):
        levelname = record.levelname
        levelname_color = self.COLOR_CODE.get(levelname, "")
        
        # Format timestamp, level, and message separately
        timestamp = f"{self.TIMESTAMP_COLOR}{self.formatTime(record, self.datefmt)}{self.RESET_COLOR}"
        levelname = f"{levelname_color}{levelname}{self.RESET_COLOR}"
        message = f"{record.getMessage()}"

        # Return the formatted log with consistent message color and different level/timestamp color
        formatted_log = f"{timestamp} [{levelname}] {message}"
        return formatted_log

# Setup Logging with colors and custom format
logging.getLogger().setLevel(logging.INFO)
formatter = ColoredLevelFormatter(datefmt='%Y-%m-%d %H:%M:%S')
console = logging.StreamHandler()
console.setFormatter(formatter)
logger = logging.getLogger()
logger.addHandler(console)

# Path to ChromeDriver
chrome_driver_path = "/usr/bin/chromedriver"

# Create Chrome driver with headless options
def create_chrome_driver():
    chrome_options = Options()

    # Declare options
    options = [
        "--headless",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        (
            f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            f"AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36"
        )
    ]

    # Add all options
    for option in options:
        chrome_options.add_argument(option)
        
    service = Service(chrome_driver_path)
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver

# Click on 'See more' button if necessary
def click_see_more(driver):
    try:
        see_more_button = driver.find_element(By.ID, "button-list-more")
        if see_more_button:
            see_more_button.click()
    except NoSuchElementException:
        pass

# Get download link for a specific version from Uptodown
def get_download_link(version: str) -> str:
    url = "https://youtube.en.uptodown.com/android/versions"
    driver = create_chrome_driver()
    driver.get(url)
    soup = BeautifulSoup(driver.page_source, "html.parser")

    while True:
        divs = soup.find_all("div", {"data-url": True})
        for div in divs:
            version_span = div.find("span", class_="version")
            if version_span and version_span.text.strip() == version:
                dl_url = div["data-url"]
                driver.get(dl_url)

                # Parse the download page for the actual download link
                soup = BeautifulSoup(driver.page_source, "html.parser")
                download_button = soup.find('button', {'id': 'detail-download-button'})
                if download_button and download_button["data-url"]:
                    data_url = download_button["data-url"]
                    full_url = f"https://dw.uptodown.com/dwn/{data_url}"
                    driver.quit()
                    return full_url

        # If the "See more" button is available, click to load more versions
        click_see_more(driver)
        soup = BeautifulSoup(driver.page_source, "html.parser")

    driver.quit()
    return None

def download_resource(url: str, filename: str) -> str:
    filepath = os.path.join("./", filename)
    
    # Add User-Agent header
    headers = {
        'User-Agent': (
            f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            f"AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36"
        )
    }

    response = requests.get(url, headers=headers, stream=True)
    
    # Check if the request was successful
    if response.status_code == 200:
        final_url = response.url  # Get final URL after any redirections
        total_size = int(response.headers.get('Content-Length', 0))  # Get the total file size
        downloaded_size = 0

        with open(filepath, 'wb') as apk_file:
            for chunk in response.iter_content(chunk_size=1024):
                if chunk:  # Filter out keep-alive chunks
                    apk_file.write(chunk)
                    downloaded_size += len(chunk)        
        
        # Logging the download progress
        logging.info(
            f"URL: {final_url} [{downloaded_size}/{total_size}] -> \"{filename}\" [1]"
        )
        return filepath
    else:
        logging.error(f"Failed to download APK. Status code: {response.status_code}")
        return None

# Function to run the Java command
def run_java_command(cli, patches, input_apk, version):
    output_apk = f'youtube-revanced-v{version}.apk'
    
    lib_command = [
        'zip',
        '--delete',
        input_apk,
        'lib/x86/*',
        'lib/x86_64/*',
        'lib/armeabi-v7a/*',
    ]
     
    patch_command = [
        'java', '-jar', cli, 'patch',
        '--patches', patches,      # ReVanced patches
        input_apk,                 # Original YouTube APK
        '--out', output_apk        # Output APK
    ]
    
    try:
        # Run the lib_command first to delete unnecessary libs
        logging.info(f"Remove some architectures...")
        process_lib = subprocess.Popen(lib_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        # Print stdout and stderr in real-time with flush
        for line in iter(process_lib.stdout.readline, b''):
            print(line.decode().strip(), flush=True)  # Direct print for stdout with flush
        
        for line in iter(process_lib.stderr.readline, b''):
            print(f"ERROR: {line.decode().strip()}", flush=True)  # Direct print for stderr with flush
        
        process_lib.stdout.close()
        process_lib.stderr.close()
        process_lib.wait()

        if process_lib.returncode != 0:
            logging.error(f"Lib command exited with return code: {process_lib.returncode}")
            return None  # Exit if lib_command fails

        # Now run the patch command
        logging.info(f"Patch {input_apk} with ReVanced patches...")
        process_patch = subprocess.Popen(patch_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # Print stdout and stderr in real-time with flush
        for line in iter(process_patch.stdout.readline, b''):
            print(line.decode().strip(), flush=True)  # Direct print for stdout with flush
        
        for line in iter(process_patch.stderr.readline, b''):
            print(f"ERROR: {line.decode().strip()}", flush=True)  # Direct print for stderr with flush
        
        process_patch.stdout.close()
        process_patch.stderr.close()
        process_patch.wait()

        if process_patch.returncode != 0:
            logging.error(f"Patch command exited with return code: {process_patch.returncode}")
            return None  # Exit if patch_command fails

        logging.info(f"Successfully patched APK to {output_apk}.")
        return output_apk  # Return the path to the output APK

    except Exception as e:
        logging.error(f"Exception occurred: {e}")
        return None
        
# Main function to download APK from Uptodown based on patches.json versions
def download_uptodown(cli, patches):
    output = subprocess.check_output([
        'java', '-jar', cli, 
        'list-versions',
        '-f', 'com.google.android.youtube',
        patches
    ])
    output = output.decode('utf-8')

    # Find all versions supported 
    versions = [
        line.split(' ')[0].strip()
        for line in output.splitlines()[2:]
        if 'Any' not in line and line.split(' ')[0].strip()
    ]

    version = max(versions, key=lambda v: list(map(int, v.split('.'))))
    download_link = get_download_link(version)
    filename = f"youtube-v{version}.apk"
        
    file_path = download_resource(download_link, filename)
    return file_path, version  # Return both the file path and version
    
# Download ReVanced assets from GitHub and return the paths of the downloaded files
def download_assets_from_repo(release_url):
    driver = create_chrome_driver()
    driver.get(release_url)
    
    downloaded_files = []
    
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.ID, "repo-content-pjax-container"))
        )
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

        asset_links = WebDriverWait(driver, 15).until(
            EC.presence_of_all_elements_located((By.XPATH, "//a[contains(@href, '/releases/download/')]"))
        )

        for link in asset_links:
            asset_url = link.get_attribute('href')
            response = requests.head(asset_url, allow_redirects=True)
            if response.status_code == 200:
                download_response = requests.get(asset_url, allow_redirects=True, stream=True)
                final_url = download_response.url  # Get the final URL after any redirections
                filename = asset_url.split('/')[-1]
                total_size = int(download_response.headers.get('Content-Length', 0))
                downloaded_size = 0

                with open(filename, 'wb') as file:
                    for chunk in download_response.iter_content(chunk_size=1024):
                        if chunk:
                            file.write(chunk)
                            downloaded_size += len(chunk)

                # Logging the download progress with final_url
                logging.info(
                    f"URL:{final_url} [{downloaded_size}/{total_size}] -> \"{filename}\" [1]"
                )
                downloaded_files.append(filename)  # Store downloaded filename
    except Exception as e:
        logging.error(f"Error while downloading from {release_url}: {e}")
    finally:
        driver.quit()
    
    return downloaded_files  # Return the list of downloaded files

# Extract version from the file name
def extract_version(file_path):
    if file_path:
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        match = re.search(r'(\d+\.\d+\.\d+(-[a-z]+\.\d+)?(-release\d*)?)', base_name)
        if match:
            return match.group(1)
    return 'unknown'

# Create GitHub release function
def create_github_release(app_name, download_files, apk_file_path):
    patch_file_path = download_files["revanced-patches"]
    cli_file_path = download_files["revanced-cli"]

    patchver = extract_version(patch_file_path)
    cliver = extract_version(cli_file_path)
    tag_name = f"{app_name}-v{patchver}"

    if not apk_file_path:
        logging.error("APK file not found, skipping release.")
        return

    # Get existing release by tag name
    existing_release_response = requests.get(
        f"https://api.github.com/repos/{repository}/releases/tags/{tag_name}",
        headers={"Authorization": f"token {github_token}"}
    )
    
    existing_release = existing_release_response.json()
    
    if "id" in existing_release:
        existing_release_id = existing_release["id"]
        logging.info(f"Updating existing release: {existing_release_id}")
        
        # Check and delete existing asset if it has the same name
        existing_assets_response = requests.get(
            f"https://api.github.com/repos/{repository}/releases/{existing_release_id}/assets",
            headers={"Authorization": f"token {github_token}"}
        )
        existing_assets = existing_assets_response.json()

        for asset in existing_assets:
            if asset['name'] == os.path.basename(apk_file_path):
                delete_asset_response = requests.delete(
                    f"https://api.github.com/repos/{repository}/releases/assets/{asset['id']}",
                    headers={"Authorization": f"token {github_token}"}
                )
                if delete_asset_response.status_code == 204:
                    logging.info(f"Successfully deleted existing asset: {asset['name']}")
                else:
                    logging.error(
                        f"Failed to delete existing asset: {asset['name']} - {delete_asset_response.json()}"
                    )
        
    else:
        # Create new release if it doesn't exist
        release_body = f"""
# Release Notes

## Build Tools:
- **ReVanced Patches:** v{patchver}
- **ReVanced CLI:** v{cliver}

## Note:
**ReVanced GmsCore** is **necessary** to work. 
- Please **download** it from [HERE](https://github.com/revanced/gmscore/releases/latest).
        """
        release_name = f"{app_name} v{patchver}"

        release_data = {
            "tag_name": tag_name,
            "target_commitish": "main",
            "name": release_name,
            "body": release_body
        }
        new_release = requests.post(
            f"https://api.github.com/repos/{repository}/releases",
            headers={
                "Authorization": f"token {github_token}",
                "Content-Type": "application/json"
            },
            data=json.dumps(release_data)
        ).json()

        existing_release_id = new_release["id"]

    # Upload new APK file
    upload_url_apk = (
        f"https://uploads.github.com/repos/{repository}/releases/"
        f"{existing_release_id}/assets?name={os.path.basename(apk_file_path)}"
    )
    with open(apk_file_path, 'rb') as apk_file:
        apk_file_content = apk_file.read()

    response = requests.post(
        upload_url_apk,
        headers={
            "Authorization": f"token {github_token}",
            "Content-Type": "application/vnd.android.package-archive"
        },
        data=apk_file_content
    )

    if response.status_code == 201:
        logging.info(f"Successfully uploaded {apk_file_path} to GitHub release.")
    else:
        logging.error(f"Failed to upload {apk_file_path}. Status code: {response.status_code}")

# Function to run the build process
def run_build():
    logging.info("Running build process...")

    # List of repositories to download assets from
    repositories = [
        "https://github.com/ReVanced/revanced-patches/releases/latest",
        "https://github.com/ReVanced/revanced-cli/releases/latest"
    ]

    # Download the assets
    all_downloaded_files = []
    for repo in repositories:
        downloaded_files = download_assets_from_repo(repo)
        all_downloaded_files.extend(downloaded_files)  # Combine all downloaded files

    # After downloading, find the necessary files
    find_file = lambda keyword, extension: next(
        filter(
            lambda f: keyword in f and f.endswith(extension), all_downloaded_files
        )
    )

    cli = find_file('revanced-cli', '.jar')
    patches = find_file('patches', '.rvp')
    
    
    # Ensure we have the required files
    if not cli or not patches:
        logging.error("Failed to download necessary ReVanced files.")
    else:
        # Download the YouTube APK
        input_apk, version = download_uptodown(cli, patches)

        if input_apk:
            # Run the patching process
            output_apk = run_java_command(cli, patches, input_apk, version)
            if output_apk:
                logging.info(f"Successfully created the patched APK: {output_apk}")

                # Prepare download files for the release
                download_files = {
                    "revanced-patches": patches,
                    "revanced-cli": cli
                }

                # Create GitHub release
                create_github_release("ReVanced", download_files, output_apk)
            else:
                logging.error("Failed to patch the APK.")
        else:
            logging.error("Failed to download the YouTube APK.")

    
# Function to get the latest release version from a GitHub repository
def get_latest_release_version(repo: str) -> str:
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    headers = {"Authorization": f"token {github_token}"}
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            latest_release = response.json()
            tag_name = latest_release['tag_name']  # Extract tag name (version) from the latest release
            return extract_version_from_tag(tag_name)  # Extract numerical version from tag
        else:
            logging.error(f"Failed to fetch latest release version from {repo}: {response.status_code}")
            return None
    except Exception as e:
        logging.error(f"Exception occurred while fetching release from {repo}: {e}")
        return None

# Extract numerical version from a tag (e.g., v4.16.0-release to 4.16.0)
def extract_version_from_tag(tag: str) -> str:
    match = re.search(r'(\d+\.\d+\.\d+)', tag)
    if match:
        return match.group(1)
    return None

# Function to compare the versions of revanced-patches repository and the current repository
def compare_repository_versions(repo_patches: str):
    version_patches = get_latest_release_version(repo_patches)
    version_current = get_latest_release_version(repository)  # Current repository
    
    if version_patches and version_current:
        if version_patches == version_current:
            logging.warning("Patched!!!Skipping build...")
            return True  # Skip build if versions are the same
        else:
            return False  # Run build if versions differ
    else:
        return False  # Run build if either repository fails to respond


# Main execution
if __name__ == "__main__":    
    # Define the repository to compare
    repo_patches = "ReVanced/revanced-patches"

    # Compare versions
    skip_build = compare_repository_versions(repo_patches)

    if not skip_build:
        run_build()  # Only run build if versions differ or repository doesn't respond
