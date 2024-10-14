import logging
import requests
import subprocess
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException
from bs4 import BeautifulSoup
import os
import json
import re

# Environment variables for GitHub token and repository
github_token = os.getenv('GITHUB_TOKEN')
repository = os.getenv('GITHUB_REPOSITORY')

# Setup logging
class ColoredLevelFormatter(logging.Formatter):
    COLOR_CODE = {
        'WARNING':  "\x1b[31m",
    }

    def format(self, record):
        levelname = record.levelname
        levelname_color = self.COLOR_CODE.get(levelname, "")
        reset_color = "\x1b[0m"
        log_msg = super().format(record)
        colored_log_msg = f"{levelname_color}{log_msg}{reset_color}"
        return colored_log_msg

# Setup Logging Level Color
logging.getLogger().setLevel(logging.INFO)
formatter = ColoredLevelFormatter("%(asctime)s %(message)s", datefmt='%Y-%m-%d %H:%M:%S')
console = logging.StreamHandler()
console.setFormatter(ColoredLevelFormatter("%(asctime)s %(message)s", datefmt='%Y-%m-%d %H:%M:%S'))
logger = logging.getLogger()
logger.addHandler(console)

# Path to ChromeDriver
chrome_driver_path = "/usr/bin/chromedriver"

# Create Chrome driver with headless options
def create_chrome_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument(
        f"user-agent=Mozilla/5.0 (Android 13; Mobile; rv:125.0) Gecko/125.0 Firefox/125.0"
    )
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
                if download_button and download_button.get('data-url'):
                    data_url = download_button.get('data-url')
                    full_url = f"https://dw.uptodown.com/dwn/{data_url}"
                    driver.quit()
                    return full_url

        # If the "See more" button is available, click to load more versions
        click_see_more(driver)
        soup = BeautifulSoup(driver.page_source, "html.parser")

    driver.quit()
    return None

# Download the APK or resource
def download_resource(url: str, filename: str) -> str:
    filepath = os.path.join("./", filename)
    
    # Add User-Agent header
    headers = {
        'User-Agent': 'Mozilla/5.0 (Android 13; Mobile; rv:125.0) Gecko/125.0 Firefox/125.0'
    }
    
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        with open(filepath, 'wb') as apk_file:
            apk_file.write(response.content)
        logging.info(f"Downloaded {filename} successfully.")
        return filepath
    else:
        logging.error(f"Failed to download APK. Status code: {response.status_code}")
        return None

# Function to run the Java command
def run_java_command(cli_jar, patches_jar, integrations_apk, input_apk, version):
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
        'java', '-jar', cli_jar, 'patch',
        '-b', patches_jar,      # ReVanced patches
        '-m', integrations_apk, # ReVanced integrations APK
        input_apk,              # Original YouTube APK
        '-o', output_apk        # Output APK
    ]
    
    try:
        # Run the lib_command first to delete unnecessary libs
        process_lib = subprocess.Popen(lib_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        for line in iter(process_lib.stdout.readline, b''):
            logging.info(line.decode().strip())
        
        for line in iter(process_lib.stderr.readline, b''):
            logging.error(line.decode().strip())
        
        process_lib.stdout.close()
        process_lib.stderr.close()
        process_lib.wait()

        if process_lib.returncode != 0:
            logging.error(f"Lib command exited with return code: {process_lib.returncode}")
            return None  # Exit if lib_command fails

        # Now run the patch command
        process_patch = subprocess.Popen(patch_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        for line in iter(process_patch.stdout.readline, b''):
            logging.info(line.decode().strip())
        
        for line in iter(process_patch.stderr.readline, b''):
            logging.error(line.decode().strip())
        
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
def download_uptodown():
    with open("./patches.json", "r") as patches_file:
        patches = json.load(patches_file)

        versions = set()
        for patch in patches:
            compatible_packages = patch.get("compatiblePackages")
            if compatible_packages and isinstance(compatible_packages, list):
                for package in compatible_packages:
                    if (
                        package.get("name") == "com.google.android.youtube" and
                        package.get("versions") is not None and
                        isinstance(package["versions"], list) and
                        package["versions"]
                    ):
                        versions.update(
                            map(str.strip, package["versions"])
                        )
                        
        version = sorted(versions, reverse=True)[0]  # Use the latest version
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
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.ID, "repo-content-pjax-container")))
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

        asset_links = WebDriverWait(driver, 15).until(
            EC.presence_of_all_elements_located((By.XPATH, "//a[contains(@href, '/releases/download/')]"))
        )

        for link in asset_links:
            asset_url = link.get_attribute('href')
            if not asset_url.endswith('.asc'):  # Skip signature files
                response = requests.head(asset_url, allow_redirects=True)
                if response.status_code == 200:
                    download_response = requests.get(asset_url, allow_redirects=True)
                    filename = asset_url.split('/')[-1]
                    with open(filename, 'wb') as file:
                        file.write(download_response.content)
                    logging.info(f"Downloaded {filename} successfully.")
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
    integrations_file_path = download_files["revanced-integrations"]
    cli_file_path = download_files["revanced-cli"]

    patchver = extract_version(patch_file_path)
    integrationsver = extract_version(integrations_file_path)
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
                    logging.error(f"Failed to delete existing asset: {asset['name']} - {delete_asset_response.json()}")
        
    else:
        # Create new release if it doesn't exist
        release_body = f"""
# Release Notes

## Build Tools:
- **ReVanced Patches:** v{patchver}
- **ReVanced Integrations:** v{integrationsver}
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
    upload_url_apk = f"https://uploads.github.com/repos/{repository}/releases/{existing_release_id}/assets?name={os.path.basename(apk_file_path)}"
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
        "https://github.com/ReVanced/revanced-cli/releases/latest",
        "https://github.com/ReVanced/revanced-integrations/releases/latest"
    ]

    # Download the assets
    all_downloaded_files = []
    for repo in repositories:
        downloaded_files = download_assets_from_repo(repo)
        all_downloaded_files.extend(downloaded_files)  # Combine all downloaded files

    # After downloading, find the necessary files
    cli_jar_files = [f for f in all_downloaded_files if 'revanced-cli' in f and f.endswith('.jar')]
    patches_jar_files = [f for f in all_downloaded_files if 'revanced-patches' in f and f.endswith('.jar')]
    integrations_apk_files = [f for f in all_downloaded_files if 'revanced-integrations' in f and f.endswith('.apk')]

    # Ensure we have the required files
    if not cli_jar_files or not patches_jar_files or not integrations_apk_files:
        logging.error("Failed to download necessary ReVanced files.")
    else:
        cli_jar = cli_jar_files[0]  # Get the first (and probably only) CLI JAR
        patches_jar = patches_jar_files[0]  # Get the first patches JAR
        integrations_apk = integrations_apk_files[0]  # Get the first integrations APK

        # Download the YouTube APK
        input_apk, version = download_uptodown()

        if input_apk:
            # Run the patching process
            output_apk = run_java_command(cli_jar, patches_jar, integrations_apk, input_apk, version)
            if output_apk:
                logging.info(f"Successfully created the patched APK: {output_apk}")

                # Prepare download files for the release
                download_files = {
                    "revanced-patches": patches_jar,
                    "revanced-integrations": integrations_apk,
                    "revanced-cli": cli_jar
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
    headers = {"Authorization": f"token {os.getenv('GITHUB_TOKEN')}"}
    
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
