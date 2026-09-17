# This file is responsible for configuring your application
# and its dependencies with the aid of the Config module.
#
# This configuration file is loaded before any dependency and
# is restricted to this project.

# General application configuration
import Config

config :coffer,
  ecto_repos: [Coffer.Repo],
  generators: [timestamp_type: :utc_datetime, binary_id: true]

# 00:05 on 1 Jan (spec §6) — fixed FY boundary lives in Coffer.FiscalYear,
# this just decides when the worker runs, not what a fiscal year means.
config :coffer, Oban,
  engine: Oban.Engines.Basic,
  notifier: Oban.Notifiers.Postgres,
  repo: Coffer.Repo,
  plugins: [
    {Oban.Plugins.Cron,
     crontab: [
       {"5 0 1 1 *", Coffer.Budgets.FiscalYearRolloverWorker},
       {"10 0 * * *", Coffer.Contracts.ContractRenewalWorker},
       {"15 0 * * *", Coffer.Inventory.CheckoutOverdueWorker}
     ]}
  ],
  queues: [default: 10]

# Configure the endpoint
config :coffer, CofferWeb.Endpoint,
  url: [host: "localhost"],
  adapter: Bandit.PhoenixAdapter,
  render_errors: [
    formats: [html: CofferWeb.ErrorHTML, json: CofferWeb.ErrorJSON],
    layout: false
  ],
  pubsub_server: Coffer.PubSub,
  live_view: [signing_salt: "aXYVO0MM"]

# Configure LiveView
config :phoenix_live_view,
  # the attribute set on all root tags. Used for Phoenix.LiveView.ColocatedCSS.
  root_tag_attribute: "phx-r"

# Configure the mailer
#
# By default it uses the "Local" adapter which stores the emails
# locally. You can see the emails in your browser, at "/dev/mailbox".
#
# For production it's recommended to configure a different adapter
# at the `config/runtime.exs`.
config :coffer, Coffer.Mailer, adapter: Swoosh.Adapters.Local

# Configure esbuild (the version is required)
config :esbuild,
  version: "0.25.4",
  coffer: [
    args:
      ~w(js/app.js --bundle --target=es2022 --outdir=../priv/static/assets/js --external:/fonts/* --external:/images/* --alias:@=.),
    cd: Path.expand("../assets", __DIR__),
    env: %{"NODE_PATH" => [Path.expand("../deps", __DIR__), Mix.Project.build_path()]}
  ]

# Configure tailwind (the version is required)
config :tailwind,
  version: "4.3.0",
  coffer: [
    args: ~w(
      --input=assets/css/app.css
      --output=priv/static/assets/css/app.css
    ),
    cd: Path.expand("..", __DIR__),
    env: %{"NODE_PATH" => [Path.expand("../deps", __DIR__), Mix.Project.build_path()]}
  ]

# Configure Elixir's Logger
config :logger, :default_formatter,
  format: "$time $metadata[$level] $message\n",
  metadata: [:request_id]

# Use Jason for JSON parsing in Phoenix
config :phoenix, :json_library, Jason

# Import environment specific config. This must remain at the bottom
# of this file so it overrides the configuration defined above.
import_config "#{config_env()}.exs"
