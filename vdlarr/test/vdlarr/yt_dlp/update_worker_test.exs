defmodule Vdlarr.YtDlp.UpdateWorkerTest do
  use Vdlarr.DataCase

  alias Vdlarr.Settings
  alias Vdlarr.YtDlp.UpdateWorker

  setup do
    Settings.set(yt_dlp_update_policy: "stable")

    :ok
  end

  describe "perform/1 for a normal scheduled run" do
    test "calls the yt-dlp runner to update yt-dlp" do
      stub(HTTPClientMock, :get, fn _url, _headers -> {:ok, ~s({"tag_name": "2025.06.01"})} end)
      expect(YtDlpRunnerMock, :update, fn "2025.06.01" -> {:ok, ""} end)
      expect(YtDlpRunnerMock, :version, fn -> {:ok, ""} end)

      perform_job(UpdateWorker, %{})
    end

    test "saves the new version to the database" do
      stub(HTTPClientMock, :get, fn _url, _headers -> {:ok, ~s({"tag_name": "2025.06.01"})} end)
      expect(YtDlpRunnerMock, :update, fn "2025.06.01" -> {:ok, ""} end)
      expect(YtDlpRunnerMock, :version, fn -> {:ok, "1.2.3"} end)

      perform_job(UpdateWorker, %{})

      assert {:ok, "1.2.3"} = Settings.get(:yt_dlp_version)
    end
  end

  describe "perform/1 when applying a policy change" do
    test "calls the yt-dlp runner to update yt-dlp" do
      Settings.set(yt_dlp_update_policy: "nightly")

      expect(YtDlpRunnerMock, :update, fn "nightly" -> {:ok, ""} end)
      expect(YtDlpRunnerMock, :version, fn -> {:ok, ""} end)

      perform_job(UpdateWorker, %{apply_policy: true})
    end
  end

  describe "kickoff/0" do
    test "enqueues a job without apply_policy" do
      assert {:ok, job} = UpdateWorker.kickoff()

      refute Map.get(job.args, "apply_policy", false)
    end
  end

  describe "kickoff_apply/0" do
    test "enqueues a job with apply_policy" do
      assert {:ok, job} = UpdateWorker.kickoff_apply()

      assert job.args[:apply_policy] == true
    end
  end
end
