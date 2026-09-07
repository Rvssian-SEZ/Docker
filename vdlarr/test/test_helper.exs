Mox.defmock(YtDlpRunnerMock, for: Vdlarr.YtDlp.YtDlpCommandRunner)
Application.put_env(:vdlarr, :yt_dlp_runner, YtDlpRunnerMock)

Mox.defmock(AppriseRunnerMock, for: Vdlarr.Lifecycle.Notifications.AppriseCommandRunner)
Application.put_env(:vdlarr, :apprise_runner, AppriseRunnerMock)

Mox.defmock(HTTPClientMock, for: Vdlarr.HTTP.HTTPBehaviour)
Application.put_env(:vdlarr, :http_client, HTTPClientMock)

Mox.defmock(UserScriptRunnerMock, for: Vdlarr.Lifecycle.UserScripts.UserScriptCommandRunner)
Application.put_env(:vdlarr, :user_script_runner, UserScriptRunnerMock)

ExUnit.start()
Ecto.Adapters.SQL.Sandbox.mode(Vdlarr.Repo, :manual)
Faker.start()

ExUnit.after_suite(fn _ ->
  File.rm_rf!(Application.get_env(:vdlarr, :media_directory))
  File.rm_rf!(Application.get_env(:vdlarr, :metadata_directory))
  File.rm_rf!(Application.get_env(:vdlarr, :extras_directory))
  File.rm_rf!(Application.get_env(:vdlarr, :tmpfile_directory))

  File.mkdir_p!(Application.get_env(:vdlarr, :media_directory))
  File.mkdir_p!(Application.get_env(:vdlarr, :metadata_directory))
  File.mkdir_p!(Application.get_env(:vdlarr, :extras_directory))
  File.mkdir_p!(Application.get_env(:vdlarr, :tmpfile_directory))
end)
