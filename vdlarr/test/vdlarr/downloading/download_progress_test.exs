defmodule Vdlarr.Downloading.DownloadProgressTest do
  use Vdlarr.DataCase

  alias Vdlarr.Downloading.DownloadState
  alias Vdlarr.Downloading.DownloadProgress
  alias Vdlarr.Downloading.DownloadProgressStore

  setup do
    VdlarrWeb.Endpoint.subscribe("downloads:progress")

    :ok
  end

  describe "handle_line/2" do
    test "broadcasts decoded progress for a matching line" do
      line = ~s(PROGRESS_JSON:{"status": "downloading", "downloaded_bytes": 100, "total_bytes": 200})

      assert :ok = DownloadProgress.handle_line(1234, line)

      assert_receive %Phoenix.Socket.Broadcast{
        topic: "downloads:progress",
        event: "progress",
        payload: %{
          media_item_id: 1234,
          progress: %{"status" => "downloading", "downloaded_bytes" => 100, "total_bytes" => 200}
        }
      }
    end

    test "includes the download's updated state and keeps it in the store" do
      DownloadProgress.handle_line(1234, "[info] abc: Downloading 1 format(s): 137+140")
      DownloadProgress.handle_line(1234, ~s(PROGRESS_JSON:{"filename": "/tmp/v.f137.mp4", "downloaded_bytes": 1}))

      assert_receive %Phoenix.Socket.Broadcast{
        topic: "downloads:progress",
        payload: %{media_item_id: 1234, state: %DownloadState{phase: :downloading, stream_index: 1}}
      }

      assert %DownloadState{format_ids: ["137", "140"]} = DownloadProgressStore.get(1234)
    end

    test "broadcasts status lines with the updated state" do
      VdlarrWeb.Endpoint.subscribe("downloads:status")

      DownloadProgress.handle_line(1234, ~s([Merger] Merging formats into "/tmp/v.mp4"))

      assert_receive %Phoenix.Socket.Broadcast{
        topic: "downloads:status",
        payload: %{media_item_id: 1234, line: "[Merger]" <> _, state: %DownloadState{phase: :merging}}
      }
    end

    test "ignores lines without the progress prefix" do
      assert :ok = DownloadProgress.handle_line(1234, "some unrelated yt-dlp warning")

      refute_receive %Phoenix.Socket.Broadcast{}
    end

    test "ignores lines with the prefix but malformed JSON" do
      assert :ok = DownloadProgress.handle_line(1234, "PROGRESS_JSON:not json")

      refute_receive %Phoenix.Socket.Broadcast{}
    end
  end
end
