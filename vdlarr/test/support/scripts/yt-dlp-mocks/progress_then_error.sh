#!/bin/bash

# Simulates a download that emits some --progress-template output before
# ultimately failing (stdout/stderr combined, like yt-dlp's real behavior) -
# used to test that CommandRunner.run/5 strips the PROGRESS_JSON noise out of
# a failed command's captured output before it's used as an error message.

echo 'PROGRESS_JSON:{"status": "downloading", "downloaded_bytes": 100, "total_bytes": 300}'
echo 'WARNING: [youtube] some_id: some transient warning'
echo 'PROGRESS_JSON:{"status": "downloading", "downloaded_bytes": 300, "total_bytes": 300}'
echo 'ERROR: [youtube] some_id: the actual failure reason'

exit 1
