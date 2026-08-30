defmodule Vdlarr.Downloading.DownloadProgressTest do
  use Vdlarr.DataCase

  alias Vdlarr.Downloading.DownloadProgress

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
