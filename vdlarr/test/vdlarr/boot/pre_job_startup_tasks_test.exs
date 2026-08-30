defmodule Vdlarr.Boot.PreJobStartupTasksTest do
  use Vdlarr.DataCase

  import Vdlarr.JobFixtures

  alias Vdlarr.Settings
  alias Vdlarr.Boot.PreJobStartupTasks

  setup do
    stub(YtDlpRunnerMock, :version, fn -> {:ok, "1"} end)
    stub(AppriseRunnerMock, :version, fn -> {:ok, "2"} end)
    stub(UserScriptRunnerMock, :run, fn _event_type, _data -> {:ok, "3", 0} end)

    :ok
  end

  describe "ensure_tmpfile_directory" do
    test "creates the tmpfile directory if it doesn't exist" do
      tmpfile_dir = Application.get_env(:vdlarr, :tmpfile_directory)
      File.rm_rf!(tmpfile_dir)

      refute File.exists?(tmpfile_dir)

      PreJobStartupTasks.init(%{})

      assert File.exists?(tmpfile_dir)
    end
  end

  describe "reset_executing_jobs" do
    test "resets executing jobs" do
      job = job_fixture()
      Repo.update_all(Oban.Job, set: [state: "executing"])

      assert Repo.reload!(job).state == "executing"

      PreJobStartupTasks.init(%{})

      assert Repo.reload!(job).state == "retryable"
    end
  end

  describe "create_blank_yt_dlp_files" do
    test "creates a blank cookie file" do
      base_dir = Application.get_env(:vdlarr, :extras_directory)
      filepath = Path.join(base_dir, "cookies.txt")
      File.rm(filepath)

      refute File.exists?(filepath)

      PreJobStartupTasks.init(%{})

      assert File.exists?(filepath)
    end

    test "creates a blank yt-dlp config file" do
      base_dir = Application.get_env(:vdlarr, :extras_directory)
      filepath = Path.join([base_dir, "yt-dlp-configs", "base-config.txt"])
      File.rm(filepath)

      refute File.exists?(filepath)

      PreJobStartupTasks.init(%{})

      assert File.exists?(filepath)
    end
  end

  describe "create_blank_user_script_file" do
    test "creates a blank script file" do
      base_dir = Application.get_env(:vdlarr, :extras_directory)
      filepath = Path.join([base_dir, "user-scripts", "lifecycle"])
      File.rm(filepath)

      refute File.exists?(filepath)

      PreJobStartupTasks.init(%{})

      assert File.exists?(filepath)
    end

    test "gives it 755 permissions" do
      base_dir = Application.get_env(:vdlarr, :extras_directory)
      filepath = Path.join([base_dir, "user-scripts", "lifecycle"])
      File.rm(filepath)

      PreJobStartupTasks.init(%{})

      assert File.stat!(filepath).mode == 0o100755
    end
  end

  describe "apply_default_settings" do
    test "sets yt_dlp version" do
      File.rm_rf!(Application.get_env(:vdlarr, :tmpfile_directory))
      Settings.set(yt_dlp_version: nil)

      refute Settings.get!(:yt_dlp_version)

      PreJobStartupTasks.init(%{})

      assert Settings.get!(:yt_dlp_version)
    end

    test "sets apprise version" do
      File.rm_rf!(Application.get_env(:vdlarr, :tmpfile_directory))
      Settings.set(apprise_version: nil)

      refute Settings.get!(:apprise_version)

      PreJobStartupTasks.init(%{})

      assert Settings.get!(:apprise_version)
    end
  end

  describe "apply_timezone_setting" do
    setup do
      original_timezone = Application.get_env(:vdlarr, :timezone)
      on_exit(fn -> Application.put_env(:vdlarr, :timezone, original_timezone) end)

      :ok
    end

    test "seeds the setting from Application.env when no timezone has been persisted yet" do
      Settings.set(timezone: nil)
      Application.put_env(:vdlarr, :timezone, "America/New_York")

      PreJobStartupTasks.init(%{})

      assert Settings.get!(:timezone) == "America/New_York"
    end

    test "re-applies a persisted timezone into Application.env, overriding the boot-time env value" do
      Settings.set(timezone: "America/New_York")
      Application.put_env(:vdlarr, :timezone, "UTC")

      PreJobStartupTasks.init(%{})

      assert Application.get_env(:vdlarr, :timezone) == "America/New_York"
    end
  end

  describe "run_app_init_script" do
    test "calls the app_init user script runner" do
      expect(UserScriptRunnerMock, :run, fn :app_init, data ->
        assert data == %{}

        {:ok, "", 0}
      end)

      PreJobStartupTasks.init(%{})
    end
  end
end
