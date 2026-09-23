defmodule Vdlarr.Downloading.DownloadStateTest do
  use ExUnit.Case, async: true

  alias Vdlarr.Downloading.DownloadState

  defp apply_lines(lines, state \\ DownloadState.new()) do
    Enum.reduce(lines, state, fn
      {:progress, progress}, acc -> DownloadState.apply_progress(acc, progress)
      line, acc -> DownloadState.apply_status_line(acc, line)
    end)
  end

  describe "a typical video+audio download" do
    test "starts out preparing during extraction" do
      state = apply_lines(["[youtube] Extracting URL: https://youtu.be/abc", "[youtube] abc: Downloading webpage"])

      assert state.phase == :preparing
      assert state.status_line == "[youtube] abc: Downloading webpage"
    end

    test "subtitle and thumbnail fetches before the transfer aren't treated as streams" do
      state =
        apply_lines([
          "[info] abc: Downloading 1 format(s): 137+140",
          "[download] Destination: /tmp/video.en.vtt",
          {:progress, %{"filename" => "/tmp/video.en.vtt", "downloaded_bytes" => 1, "total_bytes" => 2}},
          ~s([ThumbnailsConvertor] Converting thumbnail "/tmp/video.webp" to jpg)
        ])

      assert state.phase == :preparing
      assert DownloadState.stream_position(state) == nil
    end

    test "pre-download info writes don't count as finishing up" do
      state = apply_lines(["[info] Writing video metadata as JSON to: /tmp/video.info.json"])

      assert state.phase == :preparing
    end

    test "tracks which of the two streams is transferring" do
      base = ["[info] abc: Downloading 1 format(s): 137+140", "[download] Destination: /tmp/video.f137.mp4"]

      video = apply_lines(base)
      assert video.phase == :downloading
      assert video.format_ids == ["137", "140"]
      assert DownloadState.stream_position(video) == {1, 2}

      audio = apply_lines(["[download] Destination: /tmp/video.f140.m4a"], video)
      assert DownloadState.stream_position(audio) == {2, 2}
      assert audio.progress == nil
    end

    test "matches progress updates to their stream by filename" do
      state =
        apply_lines([
          "[info] abc: Downloading 1 format(s): 137+140",
          {:progress, %{"filename" => "/tmp/video.f140.m4a", "downloaded_bytes" => 5, "total_bytes" => 10}}
        ])

      assert state.phase == :downloading
      assert DownloadState.stream_position(state) == {2, 2}
      assert state.progress["downloaded_bytes"] == 5
    end

    test "moves through merging, post-processing and finishing" do
      downloading = apply_lines(["[download] Destination: /tmp/video.f137.mp4"])

      merging = apply_lines([~s([Merger] Merging formats into "/tmp/video.mp4")], downloading)
      assert {merging.phase, merging.detail} == {:merging, "Merging video and audio"}

      # Printed right after merging - must not skip ahead to "finishing up"
      still_merging = apply_lines(["Deleting original file /tmp/video.f137.mp4 (pass -k to keep)"], merging)
      assert still_merging.phase == :merging

      metadata = apply_lines([~s([Metadata] Adding metadata to "/tmp/video.mp4")], still_merging)
      assert {metadata.phase, metadata.detail} == {:post_processing, "Embedding metadata"}

      thumbnail = apply_lines([~s([EmbedThumbnail] mutagen: Adding thumbnail to "/tmp/video.mp4")], metadata)
      assert thumbnail.detail == "Embedding thumbnail"

      finishing = apply_lines(["[info] Writing '%()j' to: /tmp/video.json"], thumbnail)
      assert {finishing.phase, finishing.detail} == {:finalizing, "Finishing up"}
    end
  end

  describe "apply_status_line/2" do
    test "reports a rate-limit sleep before the download" do
      state = apply_lines(["[download] Sleeping 12.50 seconds as required by the site..."])

      assert {state.phase, state.detail} == {:waiting, "Waiting 13s to start"}
    end

    test "ignores sleeps once the transfer has started" do
      state = apply_lines(["[download] Destination: /tmp/video.mp4", "[download] Sleeping 3.00 seconds ..."])

      assert state.phase == :downloading
    end

    test "groups all fixups under one label" do
      state = apply_lines(["[download] Destination: /tmp/video.mp4", "[FixupM3u8] Fixing MPEG-TS in MP4 container"])

      assert {state.phase, state.detail} == {:post_processing, "Fixing up container"}
    end

    test "falls back to a generic label for unknown post-processors" do
      state = apply_lines(["[download] Destination: /tmp/video.mp4", "[SomeNewThing] Doing stuff"])

      assert state.detail == "Post-processing (SomeNewThing)"
    end

    test "leaves the phase alone for unrecognised lines but keeps them as the status line" do
      state = apply_lines(["[download] Destination: /tmp/video.mp4", "WARNING: something odd"])

      assert state.phase == :downloading
      assert state.status_line == "WARNING: something odd"
    end
  end

  describe "stream_position/1" do
    test "is nil before any stream has started" do
      assert DownloadState.stream_position(DownloadState.new()) == nil
    end

    test "treats a download without a format list as a single stream" do
      state = apply_lines(["[download] Destination: /tmp/video.mp4"])

      assert DownloadState.stream_position(state) == {1, 1}
    end
  end
end
