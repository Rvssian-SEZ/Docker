defmodule Vdlarr.YtDlp.UpdateManagerTest do
  use Vdlarr.DataCase

  alias Vdlarr.Settings
  alias Vdlarr.YtDlp.UpdateManager

  setup do
    stub(YtDlpRunnerMock, :version, fn -> {:ok, "2025.01.01"} end)

    :ok
  end

  describe "policies/0" do
    test "returns the valid policies" do
      assert UpdateManager.policies() == ~w(stable nightly nightly_frozen nightly_until_stable pinned)
    end
  end

  describe "humanize_policy/1" do
    test "returns a friendly label for each known policy" do
      assert UpdateManager.humanize_policy("stable") == "Stable"
      assert UpdateManager.humanize_policy("nightly") == "Nightly"
      assert UpdateManager.humanize_policy("nightly_frozen") == "Nightly, frozen"
      assert UpdateManager.humanize_policy("nightly_until_stable") == "Nightly until stable"
      assert UpdateManager.humanize_policy("pinned") == "Pinned"
    end

    test "falls back to Stable for an unknown policy" do
      assert UpdateManager.humanize_policy("something_else") == "Stable"
    end
  end

  describe "run_scheduled_update/0 with the stable policy" do
    test "updates to the resolved latest stable version" do
      Settings.set(yt_dlp_update_policy: "stable")

      stub(HTTPClientMock, :get, fn _url, _headers -> {:ok, ~s({"tag_name": "2025.06.01"}) } end)
      expect(YtDlpRunnerMock, :update, fn "2025.06.01" -> {:ok, ""} end)

      assert :ok = UpdateManager.run_scheduled_update()
    end

    test "falls back to a channel update if the GitHub lookup fails" do
      Settings.set(yt_dlp_update_policy: "stable")

      stub(HTTPClientMock, :get, fn _url, _headers -> {:error, "network error"} end)
      expect(YtDlpRunnerMock, :update, fn "stable" -> {:ok, ""} end)

      assert :ok = UpdateManager.run_scheduled_update()
    end
  end

  describe "run_scheduled_update/0 with the nightly policy" do
    test "updates to the nightly channel" do
      Settings.set(yt_dlp_update_policy: "nightly")

      expect(YtDlpRunnerMock, :update, fn "nightly" -> {:ok, ""} end)

      assert :ok = UpdateManager.run_scheduled_update()
    end
  end

  describe "run_scheduled_update/0 with the pinned policy" do
    test "re-asserts the pinned version" do
      Settings.set(yt_dlp_update_policy: "pinned")
      Settings.set(yt_dlp_pinned_version: "2025.03.03")

      expect(YtDlpRunnerMock, :update, fn "2025.03.03" -> {:ok, ""} end)

      assert :ok = UpdateManager.run_scheduled_update()
    end

    test "skips the update if no version is pinned" do
      Settings.set(yt_dlp_update_policy: "pinned")
      Settings.set(yt_dlp_pinned_version: nil)

      expect(YtDlpRunnerMock, :update, 0, fn _ -> {:ok, ""} end)

      assert :ok = UpdateManager.run_scheduled_update()
    end
  end

  describe "run_scheduled_update/0 with the nightly_frozen policy" do
    test "re-asserts the frozen nightly baseline" do
      Settings.set(yt_dlp_update_policy: "nightly_frozen")
      Settings.set(yt_dlp_nightly_baseline: "2025.03.03.123456")

      expect(YtDlpRunnerMock, :update, fn "nightly@2025.03.03.123456" -> {:ok, ""} end)

      assert :ok = UpdateManager.run_scheduled_update()
    end

    test "no-ops if no baseline is recorded" do
      Settings.set(yt_dlp_update_policy: "nightly_frozen")
      Settings.set(yt_dlp_nightly_baseline: nil)

      expect(YtDlpRunnerMock, :update, 0, fn _ -> {:ok, ""} end)

      assert :ok = UpdateManager.run_scheduled_update()
    end
  end

  describe "run_scheduled_update/0 with the nightly_until_stable policy" do
    test "reverts to stable once stable catches up to the nightly baseline" do
      Settings.set(yt_dlp_update_policy: "nightly_until_stable")
      Settings.set(yt_dlp_nightly_baseline: "2025.03.03.123456")

      stub(HTTPClientMock, :get, fn _url, _headers -> {:ok, ~s({"tag_name": "2025.03.04"}) } end)
      expect(YtDlpRunnerMock, :update, fn "2025.03.04" -> {:ok, ""} end)

      assert :ok = UpdateManager.run_scheduled_update()

      assert Settings.get!(:yt_dlp_update_policy) == "stable"
      assert Settings.get!(:yt_dlp_nightly_baseline) == nil
    end

    test "stays on nightly if stable hasn't caught up yet" do
      Settings.set(yt_dlp_update_policy: "nightly_until_stable")
      Settings.set(yt_dlp_nightly_baseline: "2025.03.03.123456")

      stub(HTTPClientMock, :get, fn _url, _headers -> {:ok, ~s({"tag_name": "2025.03.02"}) } end)
      expect(YtDlpRunnerMock, :update, fn "nightly@2025.03.03.123456" -> {:ok, ""} end)

      assert :ok = UpdateManager.run_scheduled_update()

      assert Settings.get!(:yt_dlp_update_policy) == "nightly_until_stable"
    end
  end

  describe "apply_policy/0" do
    test "captures the nightly baseline when jumping to a frozen nightly" do
      Settings.set(yt_dlp_update_policy: "nightly_frozen")

      expect(YtDlpRunnerMock, :update, fn "nightly" -> {:ok, ""} end)
      stub(YtDlpRunnerMock, :version, fn -> {:ok, "2025.03.03.123456"} end)

      assert :ok = UpdateManager.apply_policy()

      assert Settings.get!(:yt_dlp_nightly_baseline) == "2025.03.03.123456"
    end

    test "saves the refreshed installed version to settings" do
      Settings.set(yt_dlp_update_policy: "nightly")

      expect(YtDlpRunnerMock, :update, fn "nightly" -> {:ok, ""} end)
      expect(YtDlpRunnerMock, :version, fn -> {:ok, "2025.09.09.000001"} end)

      assert :ok = UpdateManager.apply_policy()

      assert Settings.get!(:yt_dlp_version) == "2025.09.09.000001"
    end
  end
end
