defmodule Vdlarr.YtDlp.BgutilPluginUpdateWorkerTest do
  use Vdlarr.DataCase

  alias Vdlarr.Settings
  alias Vdlarr.YtDlp.BgutilPluginUpdateWorker

  setup do
    plugin_directory = Path.join([System.tmp_dir!(), "test", "bgutil-plugin-update-worker-#{:erlang.unique_integer([:positive])}"])
    Application.put_env(:vdlarr, :yt_dlp_plugin_directory, plugin_directory)

    on_exit(fn ->
      Settings.set(bgutil_provider_url: nil)
      Application.put_env(:vdlarr, :yt_dlp_plugin_directory, "/config/extras")
      File.rm_rf(plugin_directory)
    end)

    %{plugin_directory: plugin_directory}
  end

  describe "perform/1" do
    test "does nothing when bgutil_provider_url isn't configured" do
      Settings.set(bgutil_provider_url: nil)

      expect(HTTPClientMock, :get, 0, fn _url, _headers, _opts -> {:ok, ""} end)

      assert :ok = perform_job(BgutilPluginUpdateWorker, %{})
    end

    test "doesn't attempt to update the plugin when versions already match", %{plugin_directory: plugin_directory} do
      Settings.set(bgutil_provider_url: "http://bgutil-provider:4416")
      write_installed_plugin_version(plugin_directory, "1.3.2")

      expect(HTTPClientMock, :get, fn "http://bgutil-provider:4416/ping", _headers, _opts ->
        {:ok, Phoenix.json_library().encode!(%{"version" => "1.3.2", "server_uptime" => 123.4})}
      end)

      assert :ok = perform_job(BgutilPluginUpdateWorker, %{})

      # Unchanged - if an update were attempted it would fail (no real network access in
      # tests) and this file's content would still be untouched either way, but this at
      # least confirms the no-op path doesn't blow up
      assert installed_version(plugin_directory) == "1.3.2"
    end

    test "logs and no-ops when the provider can't be reached" do
      Settings.set(bgutil_provider_url: "http://bgutil-provider:4416")

      expect(HTTPClientMock, :get, fn _url, _headers, _opts -> {:error, "connection refused"} end)

      assert :ok = perform_job(BgutilPluginUpdateWorker, %{})
    end
  end

  defp write_installed_plugin_version(plugin_directory, version) do
    filepath =
      Path.join([plugin_directory, "bgutil-ytdlp-pot-provider", "yt_dlp_plugins", "extractor", "getpot_bgutil.py"])

    File.mkdir_p!(Path.dirname(filepath))
    File.write!(filepath, "__version__ = '#{version}'\n")
  end

  defp installed_version(plugin_directory) do
    filepath =
      Path.join([plugin_directory, "bgutil-ytdlp-pot-provider", "yt_dlp_plugins", "extractor", "getpot_bgutil.py"])

    filepath
    |> File.read!()
    |> then(&Regex.run(~r/__version__\s*=\s*'([\d.]+)'/, &1))
    |> Enum.at(1)
  end
end
