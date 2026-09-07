defmodule Vdlarr.SettingsTest do
  use Vdlarr.DataCase

  alias Vdlarr.Settings
  alias Vdlarr.Settings.Setting

  # NOTE: We're treating some of these tests differently
  # than in other modules because certain settings
  # are always created on app boot (including in the test env),
  # so we can't treat these like a clean slate.

  setup do
    # Ensure we have a clean slate
    Settings.set(restrict_filenames: false)
    Settings.set(yt_dlp_version: nil)

    :ok
  end

  describe "record/0" do
    test "returns the only setting" do
      assert %Setting{} = Settings.record()
    end
  end

  describe "update_setting/2" do
    test "updates the setting" do
      setting = Settings.record()

      assert {:ok, false} = Settings.get(:restrict_filenames)
      assert {:ok, %Setting{}} = Settings.update_setting(setting, %{restrict_filenames: true})
      assert {:ok, true} = Settings.get(:restrict_filenames)
    end
  end

  describe "set/1" do
    test "updates the setting" do
      assert {:ok, true} = Settings.set(restrict_filenames: true)
      assert {:ok, true} = Settings.get(:restrict_filenames)
    end

    test "returns an error if the setting key doesn't exist" do
      assert {:error, :invalid_key} = Settings.set(foo: "bar")
    end

    test "returns an error if the setting value is invalid" do
      assert {:error, %Ecto.Changeset{}} = Settings.set(restrict_filenames: "bar")
    end
  end

  describe "get/1" do
    test "returns the setting value" do
      assert {:ok, false} = Settings.get(:restrict_filenames)
    end

    test "returns an error if the setting key doesn't exist" do
      assert {:error, :invalid_key} = Settings.get(:foo)
    end
  end

  describe "get!/1" do
    test "returns the setting value" do
      assert Settings.get!(:restrict_filenames) == false
    end

    test "raises an error if the setting key doesn't exist" do
      assert_raise RuntimeError, "Setting `foo` not found", fn ->
        Settings.get!(:foo)
      end
    end
  end

  describe "update_setting/2 when testing timezone" do
    setup do
      original_timezone = Application.get_env(:vdlarr, :timezone)
      on_exit(fn -> Application.put_env(:vdlarr, :timezone, original_timezone) end)

      :ok
    end

    test "accepts a valid timezone" do
      setting = Settings.record()

      assert {:ok, %Setting{timezone: "America/New_York"}} =
               Settings.update_setting(setting, %{timezone: "America/New_York"})
    end

    test "rejects an invalid timezone" do
      setting = Settings.record()

      assert {:error, changeset} = Settings.update_setting(setting, %{timezone: "Not/A_Zone"})
      assert "is not a recognized timezone" in errors_on(changeset).timezone
    end

    test "syncs Application.env so hot-path reads stay fast and up to date" do
      setting = Settings.record()

      assert {:ok, %Setting{}} = Settings.update_setting(setting, %{timezone: "America/New_York"})
      assert Application.get_env(:vdlarr, :timezone) == "America/New_York"
    end
  end

  describe "update_setting/2 when testing jellyfin settings" do
    setup do
      on_exit(fn ->
        Settings.set(jellyfin_url: nil)
        Settings.set(jellyfin_api_key: nil)
        Settings.set(jellyfin_path_prefix: nil)
      end)

      :ok
    end

    test "accepts a url, api key, and path prefix" do
      setting = Settings.record()

      assert {:ok, %Setting{} = updated} =
               Settings.update_setting(setting, %{
                 jellyfin_url: "http://jellyfin.local:8096",
                 jellyfin_api_key: "abc123",
                 jellyfin_path_prefix: "/data/youtube"
               })

      assert updated.jellyfin_url == "http://jellyfin.local:8096"
      assert updated.jellyfin_api_key == "abc123"
      assert updated.jellyfin_path_prefix == "/data/youtube"
    end

    test "all three fields are optional" do
      setting = Settings.record()

      assert {:ok, %Setting{} = updated} = Settings.update_setting(setting, %{})

      assert updated.jellyfin_url == nil
      assert updated.jellyfin_api_key == nil
      assert updated.jellyfin_path_prefix == nil
    end
  end

  describe "change_setting/2" do
    test "returns a changeset" do
      setting = Settings.record()

      assert %Ecto.Changeset{} = Settings.change_setting(setting, %{restrict_filenames: true})
    end

    test "ensures the extractor sleep interval is positive" do
      setting = Settings.record()

      assert %Ecto.Changeset{valid?: true} = Settings.change_setting(setting, %{extractor_sleep_interval_seconds: 1})
      assert %Ecto.Changeset{valid?: true} = Settings.change_setting(setting, %{extractor_sleep_interval_seconds: 0})
      assert %Ecto.Changeset{valid?: false} = Settings.change_setting(setting, %{extractor_sleep_interval_seconds: -1})
    end

    test "allows you to reset the extractor sleep interval" do
      setting = Settings.record()
      assert {:ok, setting} = Settings.update_setting(setting, %{extractor_sleep_interval_seconds: 1})

      assert %Ecto.Changeset{valid?: true} = Settings.change_setting(setting, %{extractor_sleep_interval_seconds: 0})
    end

    test "only accepts known yt_dlp_update_policy values" do
      setting = Settings.record()

      assert %Ecto.Changeset{valid?: true} = Settings.change_setting(setting, %{yt_dlp_update_policy: "nightly"})
      assert %Ecto.Changeset{valid?: false} = Settings.change_setting(setting, %{yt_dlp_update_policy: "bogus"})
    end

    test "allows setting the pinned policy before a pinned version is set" do
      # Settings.set/1 only ever updates one field at a time, so requiring
      # yt_dlp_pinned_version in the same changeset as yt_dlp_update_policy would make
      # `Settings.set(yt_dlp_update_policy: "pinned")` fail before the follow-up
      # `Settings.set(yt_dlp_pinned_version: ...)` call ever runs. UpdateManager's
      # reassert_pinned_version/0 already handles a blank pinned version safely at
      # runtime (logs and no-ops), so this is intentionally unvalidated here.
      setting = Settings.record()

      assert %Ecto.Changeset{valid?: true} = Settings.change_setting(setting, %{yt_dlp_update_policy: "pinned"})

      assert %Ecto.Changeset{valid?: true} =
               Settings.change_setting(setting, %{yt_dlp_update_policy: "pinned", yt_dlp_pinned_version: "2025.12.08"})
    end

    test "does not require a pinned version for other policies" do
      setting = Settings.record()

      assert %Ecto.Changeset{valid?: true} = Settings.change_setting(setting, %{yt_dlp_update_policy: "stable"})
    end
  end
end
