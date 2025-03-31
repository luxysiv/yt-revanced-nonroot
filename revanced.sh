#!/bin/bash
source ./utils.sh

# Function to fetch the latest release version of a GitHub repository
get_latest_release_version() {
    local repo="$1"
    local url="https://api.github.com/repos/${repo}/releases/latest"

    # Use http_request to get the latest release tag name, including the GitHub token in the header
    response=$(http_request - --header="Authorization: token $GITHUB_TOKEN" "$url" 2>/dev/null)

    # Check if the request was successful
    if [[ $? -eq 0 ]]; then
        # Extract the tag name from the response
        tag_name=$(echo "$response" | grep -oP '"tag_name":\s*"\K(v?[\d.]+)' | head -n 1)

        if [[ -n "$tag_name" ]]; then
            # Extract the version from the tag (e.g., v4.16.0-release to 4.16.0)
            echo "$tag_name" | grep -oP '\d+\.\d+\.\d+'
        else
            echo "Error: Tag name not found for $repo"
            return 1
        fi
    else
        echo "Error: Failed to fetch release version for $repo"
        return 1
    fi
}

# Function to compare versions of two repositories
compare_repository_versions() {    
    version_patches=$(get_latest_release_version "ReVanced/revanced-patches")
    version_current=$(get_latest_release_version "$GITHUB_REPOSITORY")

    if [[ -n "$version_patches" && -n "$version_current" ]]; then
        if [[ "$version_patches" == "$version_current" ]]; then
            echo "Patched! Skipping build..."
            return 0  # Skip build if versions are the same
        else
            return 1  # Run build if versions differ
        fi
    else
        return 1  # Run build if either repository fails to respond
    fi
}


# Compare versions
if ! compare_repository_versions "$repo_patches" "$repository"; then
    echo "Running build..."
    download_resources
    package="com.google.android.youtube"
    download_apk "$package"
    version=$(ls -1 | grep -oP 'youtube-v\K\d+(\.\d+)+' | head -n 1)
    apply_patches "$version"
    sign_apk "$version"
    create_github_release "$version"
fi
