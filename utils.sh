#!/bin/bash

# Function to perform HTTP requests
http_request() {
    wget --header="User-Agent: Mozilla/5.0 (Android 13; Mobile; rv:125.0) Gecko/125.0 Firefox/125.0" \
         --header="Content-Type: application/octet-stream" \
         --header="Accept-Language: en-US,en;q=0.9" \
         --header="Connection: keep-alive" \
         --header="Upgrade-Insecure-Requests: 1" \
         --header="Cache-Control: max-age=0" \
         --header="Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8" \
         --keep-session-cookies --timeout=30 -nv -O "$@"
}

# Function to get supported versions from Revanced
get_supported_versions() {
    local package_name=$1
    local output=$(java -jar revanced-cli*.jar list-versions -f "$package_name" patch*.rvp)
    local versions=$(echo "$output" | tail -n +3 | sed 's/ (.*)//' | grep -v -w "Any" | sort -rV)
    echo "$versions"
}

# Function to download necessary resources from GitHub
download_resources() {
    for repo in revanced-patches revanced-cli; do
        local github_api_url="https://api.github.com/repos/revanced/$repo/releases/latest"
        local page=$(http_request - 2>/dev/null "$github_api_url")
        local asset_urls=$(echo "$page" | jq -r '.assets[] | select(.name | endswith(".asc") | not) | "\(.browser_download_url) \(.name)"')
        while read -r download_url asset_name; do
            http_request "$asset_name" "$download_url"
        done <<< "$asset_urls"
    done
}

# Function to download the APK
download_apk() {
    local package=$1
    local base_url="https://androidapksfree.com/youtube/${package//./-}/old/page"
    local versions=($(get_supported_versions "$package"))
    local found=false

    for version in "${versions[@]}"; do
        echo "Searching for version: $version"

        local page=1
        while true; do
            local url="$base_url/$page"
            echo "Checking page $page: $url"

            local page_content=$(http_request - "$url")
            
            if [[ "$page_content" == *"404 Not Found"* ]]; then
                echo "Error 404: Page $page not found. Stopping script."
                exit 0
            fi
    
            local available_versions=($(echo "$page_content" | grep -oP '(?<=class="limit-line">)[^<]+'))

            if [ ${#available_versions[@]} -eq 0 ] || [[ "${available_versions[-1]}" < "$version" ]]; then
                echo "No matching version on page $page. Moving to next page..."
                ((page++))
                continue
            fi

            local apk_url=$(echo "$page_content" | grep -B1 "class=\"limit-line\">$version" | grep -oP 'href="\K[^"]+')

            if [ -n "$apk_url" ]; then
                echo "Found download page for version $version, fetching content..."
                local download_page=$(http_request - "$apk_url")
                local download_url=$(echo "$download_page" | grep 'class="buttonDownload box-shadow-mod"' | grep -oP 'href="\K[^"]+')

                if [ -n "$download_url" ]; then
                    echo "Downloading version: $version"
                    http_request "youtube-v$version.apk" "$download_url"
                    found=true
                    break 2
                fi
            fi

            ((page++))
        done
    done

    if [ "$found" = false ]; then
        echo "No downloadable version found."
        exit 1
    fi
}

# Function to apply patches to the APK
apply_patches() {
    local version=$1
    zip --delete "youtube-v$version.apk" "lib/x86/*" "lib/x86_64/*" "lib/armeabi-v7a/*" >/dev/null
    java -jar revanced-cli*.jar patch \
        --patches patches*.rvp \
        --out "patched-youtube-v$version.apk" \
        "youtube-v$version.apk"
    rm "youtube-v$version.apk"
}

# Function to sign the patched APK
sign_apk() {
    local version=$1
    local apksigner=$(find $ANDROID_SDK_ROOT/build-tools -name apksigner -type f | sort -r | head -n 1)
    $apksigner sign --verbose \
        --ks ./public.jks \
        --ks-key-alias public \
        --ks-pass pass:public \
        --key-pass pass:public \
        --in "patched-youtube-v$version.apk" \
        --out "youtube-revanced-v$version.apk"
    rm "patched-youtube-v$version.apk"
}

# Function to create release notes
create_release_notes() {
    local patchver=$(ls -1 patches*.rvp | grep -oP '\d+(\.\d+)+')
    local cliver=$(ls -1 revanced-cli*.jar | grep -oP '\d+(\.\d+)+')
    cat <<EOF
# Release Notes

## Build Tools:
- **ReVanced Patches:** v$patchver
- **ReVanced CLI:** v$cliver

## Note:
**ReVancedGms** is **necessary** to work. 
- Please **download** it from [HERE](https://github.com/revanced/gmscore/releases/latest).
EOF
}

# Function to create a GitHub release
create_github_release() {
    local version=$1
    local authorization="Authorization: token $GITHUB_TOKEN"
    local api_releases="https://api.github.com/repos/$GITHUB_REPOSITORY/releases"
    local upload_release="https://uploads.github.com/repos/$GITHUB_REPOSITORY/releases"
    local apk_file_path=$(find . -type f -name "youtube-revanced*.apk")
    local apk_file_name=$(basename "$apk_file_path")
    local patchver=$(ls -1 patches*.rvp | grep -oP '\d+(\.\d+)+')
    local tag_name="v$patchver"

    if [ ! -f "$apk_file_path" ]; then
        exit 1
    fi

    local existing_release=$(http_request - --header="$authorization" "$api_releases/tags/$tag_name" 2>/dev/null)

    if [ -n "$existing_release" ]; then
        local existing_release_id=$(echo "$existing_release" | jq -r ".id")
        local upload_url_apk="$upload_release/$existing_release_id/assets?name=$apk_file_name"

        for existing_asset in $(echo "$existing_release" | jq -r '.assets[].name'); do
            if [ "$existing_asset" == "$apk_file_name" ]; then
                local asset_id=$(echo "$existing_release" | jq -r '.assets[] | select(.name == "'"$apk_file_name"'") | .id')
                http_request - --header="$authorization" --method=DELETE "$api_releases/assets/$asset_id" 2>/dev/null
            fi
        done
    else
        local release_notes=$(create_release_notes)
        local release_data=$(jq -n \
            --arg tag_name "$tag_name" \
            --arg target_commitish "main" \
            --arg name "Revanced $tag_name" \
            --arg body "$release_notes" \
            '{ tag_name: $tag_name, target_commitish: $target_commitish, name: $name, body: $body }')
        local new_release=$(http_request - --header="$authorization" --post-data="$release_data" "$api_releases")
        local release_id=$(echo "$new_release" | jq -r ".id")
        local upload_url_apk="$upload_release/$release_id/assets?name=$apk_file_name"
    fi

    http_request - &>/dev/null --header="$authorization" --post-file="$apk_file_path" "$upload_url_apk"
}
