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

  @doc """
  TEST/DEMO USE ONLY — never run against a real deployment. Not part of the
  automatic boot chain (see `seed/0` for that) — must be invoked explicitly,
  typically via `docker exec` against an ALREADY-RUNNING container, so unlike
  `seed/0` (which only ever runs before `server` binds its port, as one step
  in the same boot sequence) this can't start the full `:coffer` OTP app —
  that would try to bind the Endpoint's port a second time in the same
  container and crash. `Ecto.Migrator.with_repo/2` starts only the repo
  (and its own deps), same trick `migrate/0` already relies on above.
  """
  def demo_seed do
    load_app()

    for repo <- repos() do
      {:ok, _, _} =
        Ecto.Migrator.with_repo(repo, fn _repo ->
          @app
          |> :code.priv_dir()
          |> to_string()
          |> Path.join("repo/demo_seeds.exs")
          |> Code.eval_file()
        end)
    end
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
