# This file is responsible for configuring your application
# and its dependencies with the aid of the Config module.
#
# This configuration file is loaded before any dependency and
# is restricted to this project.

# General application configuration
import Config

config :vdlarr,
  ecto_repos: [Vdlarr.Repo],
  generators: [timestamp_type: :utc_datetime],
  env: config_env(),
  # Specifying backend data here makes mocking and local testing SUPER easy
  yt_dlp_executable: System.find_executable("yt-dlp"),
  apprise_executable: System.find_executable("apprise"),
  yt_dlp_runner: Vdlarr.YtDlp.CommandRunner,
  apprise_runner: Vdlarr.Lifecycle.Notifications.CommandRunner,
  http_client: Vdlarr.HTTP.HTTPClient,
  media_directory: "/downloads",
  # The user may or may not store metadata for their needs, but the app will always store its copy
  metadata_directory: "/config/metadata",
  extras_directory: "/config/extras",
  # Where yt-dlp's system plugin directory lives - see the Dockerfile and
  # Vdlarr.YtDlp.BgutilPluginUpdateWorker
  yt_dlp_plugin_directory: "/etc/yt-dlp/plugins",
  tmpfile_directory: Path.join([System.tmp_dir!(), "vdlarr", "data"]),
  # Setting BASIC_AUTH_USERNAME and BASIC_AUTH_PASSWORD implies you want to use basic auth.
  # If either is unset, basic auth will not be used.
  basic_auth_username: "",
  basic_auth_password: "",
  expose_feed_endpoints: false,
  file_watcher_poll_interval: 1000,
  timezone: "UTC",
  base_route_path: "/"

config :vdlarr, Vdlarr.Repo,
  journal_mode: :wal,
  pool_size: 5

# Configures the endpoint
config :vdlarr, VdlarrWeb.Endpoint,
  url: [host: "localhost", port: 8945],
  # NOTE: this must be updated if ever deployed traditionally (ie: not self-hosted)
  check_origin: false,
  adapter: Phoenix.Endpoint.Cowboy2Adapter,
  render_errors: [
    formats: [html: VdlarrWeb.ErrorHTML, json: VdlarrWeb.ErrorJSON],
    root_layout: {VdlarrWeb.Layouts, :root},
    layout: {VdlarrWeb.Layouts, :app}
  ],
  pubsub_server: Vdlarr.PubSub,
  live_view: [signing_salt: "/t5878kO"]

config :vdlarr, Oban,
  engine: Oban.Engines.Lite,
  repo: Vdlarr.Repo

# Configures the mailer
#
# By default it uses the "Local" adapter which stores the emails
# locally. You can see the emails in your browser, at "/dev/mailbox".
#
# For production it's recommended to configure a different adapter
# at the `config/runtime.exs`.
config :vdlarr, Vdlarr.Mailer, adapter: Swoosh.Adapters.Local

# Configure esbuild (the version is required)
config :esbuild,
  version: "0.17.11",
  default: [
    args:
      ~w(js/app.js --bundle --target=es2017 --outdir=../priv/static/assets --external:/fonts/* --external:/images/*),
    cd: Path.expand("../assets", __DIR__),
    env: %{"NODE_PATH" => Path.expand("../deps", __DIR__)}
  ]

# Configure tailwind (the version is required)
config :tailwind,
  version: "3.4.3",
  default: [
    args: ~w(
      --config=tailwind.config.js
      --input=css/app.css
      --output=../priv/static/assets/app.css
    ),
    cd: Path.expand("../assets", __DIR__)
  ]

# Configures Elixir's Logger
config :logger, :default_formatter,
  format: "$date $time $metadata[$level] | $message\n",
  metadata: [:request_id]

# Use Jason for JSON parsing in Phoenix
config :phoenix, :json_library, Jason

config :vdlarr, Vdlarr.PromEx,
  disabled: true,
  manual_metrics_start_delay: :no_delay,
  drop_metrics_groups: [],
  metrics_server: :disabled

# Import environment specific config. This must remain at the bottom
# of this file so it overrides the configuration defined above.
import_config "#{config_env()}.exs"
