defmodule Coffer.Release do
  @moduledoc """
  Used for executing DB release tasks when run in production without Mix
  installed.
  """
  @app :coffer

  def migrate do
    load_app()

    for repo <- repos() do
      {:ok, _, _} = Ecto.Migrator.with_repo(repo, &Ecto.Migrator.run(&1, :up, all: true))
    end
  end

  def rollback(repo, version) do
    load_app()
    {:ok, _, _} = Ecto.Migrator.with_repo(repo, &Ecto.Migrator.run(&1, :down, to: version))
  end

  @doc "Idempotent seed data (e.g. the SCR base currency) — safe to run on every boot."
  def seed do
    load_app()
    Application.ensure_all_started(@app)
    # `priv_dir/1` resolves correctly regardless of CWD — the `bin/seed`
    # overlay script `cd`s into `/app/bin` before invoking this, so a
    # relative "priv/repo/seeds.exs" path silently fails to find the file.
    @app
    |> :code.priv_dir()
    |> to_string()
    |> Path.join("repo/seeds.exs")
    |> Code.eval_file()
  end

  defp repos do
    Application.fetch_env!(@app, :ecto_repos)
  end

  defp load_app do
    # Many platforms require SSL when connecting to the database
    Application.ensure_all_started(:ssl)
    Application.ensure_loaded(@app)
  end
end
