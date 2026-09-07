#!/bin/bash

# Simulates yt-dlp's --progress-template output during a download by emitting
# a few PROGRESS_JSON lines to stdout (with small delays, so a real streaming
# :line_handler can be observed receiving them before the command exits), then
# writes to the --print-to-file location the same way repeater.sh does so
# CommandRunner.run/5's File.read(output_filepath) still succeeds afterward.

echo 'PROGRESS_JSON:{"status": "downloading", "downloaded_bytes": 100, "total_bytes": 300}'
sleep 0.05
echo 'PROGRESS_JSON:{"status": "downloading", "downloaded_bytes": 300, "total_bytes": 300}'
sleep 0.05
echo 'PROGRESS_JSON:{"status": "finished", "downloaded_bytes": 300, "total_bytes": 300}'

for ((i = 1; i <= $#; i++)); do
  if [ "${!i}" == "--print-to-file" ]; then
    file_location="${@:i+2:1}"
    break
  fi
done

if [ "${!i}" == "--print-to-file" ]; then
  echo "$@" >"$file_location"
fi
