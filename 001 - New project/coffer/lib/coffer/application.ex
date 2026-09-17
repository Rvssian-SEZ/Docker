defmodule Coffer.Application do
  # See https://elixir.hexdocs.pm/Application.html
  # for more information on OTP Applications
  @moduledoc false

  use Application

  @impl true
  def start(_type, _args) do
    children = [
      CofferWeb.Telemetry,
      Coffer.Repo,
      {DNSCluster, query: Application.get_env(:coffer, :dns_cluster_query) || :ignore},
      {Phoenix.PubSub, name: Coffer.PubSub},
      {Oban, Application.fetch_env!(:coffer, Oban)},
      # Start a worker by calling: Coffer.Worker.start_link(arg)
      # {Coffer.Worker, arg},
      # Start to serve requests, typically the last entry
      CofferWeb.Endpoint
    ]

    # See https://elixir.hexdocs.pm/Supervisor.html
    # for other strategies and supported options
    opts = [strategy: :one_for_one, name: Coffer.Supervisor]
    Supervisor.start_link(children, opts)
  end

  # Tell Phoenix to update the endpoint configuration
  # whenever the application is updated.
  @impl true
  def config_change(changed, _new, removed) do
    CofferWeb.Endpoint.config_change(changed, removed)
    :ok
  end
end
