defmodule Vdlarr.Lifecycle.Notifications.JellyfinNotificationWorkerTest do
  use Vdlarr.DataCase

  import Vdlarr.MediaFixtures

  alias Vdlarr.Settings
  alias Vdlarr.Lifecycle.Notifications.JellyfinNotificationWorker

  setup do
    on_exit(fn ->
      Settings.set(jellyfin_url: nil)
      Settings.set(jellyfin_api_key: nil)
    end)

    :ok
  end

  describe "kickoff/1" do
    test "enqueues a job for the given media item" do
      media_item = media_item_fixture()

      assert {:ok, _job} = JellyfinNotificationWorker.kickoff(media_item)

      assert_enqueued(worker: JellyfinNotificationWorker, args: %{"media_item_id" => media_item.id})
    end
  end

  describe "perform/1" do
    test "notifies jellyfin about the media item" do
      Settings.set(jellyfin_url: "http://jellyfin.local:8096")
      Settings.set(jellyfin_api_key: "abc123")

      media_item = media_item_fixture(media_filepath: "/downloads/some/file.mp4")

      expect(HTTPClientMock, :post, fn url, _body, _headers, _opts ->
        assert url == "http://jellyfin.local:8096/Library/Media/Updated"

        {:ok, ""}
      end)

      assert :ok = perform_job(JellyfinNotificationWorker, %{media_item_id: media_item.id})
    end

    test "does not blow up if the media item no longer exists" do
      assert :ok = perform_job(JellyfinNotificationWorker, %{media_item_id: 0})
    end

    test "does nothing when jellyfin isn't configured" do
      Settings.set(jellyfin_url: nil)
      Settings.set(jellyfin_api_key: nil)

      media_item = media_item_fixture()

      expect(HTTPClientMock, :post, 0, fn _url, _body, _headers, _opts -> {:ok, ""} end)

      assert :ok = perform_job(JellyfinNotificationWorker, %{media_item_id: media_item.id})
    end
  end
end
