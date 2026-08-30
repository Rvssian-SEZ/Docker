defmodule Vdlarr.Repo.Migrations.AddTimezoneToSettings do
  use Ecto.Migration

  def change do
    alter table(:settings) do
      # Deliberately no default - nil means "not yet seeded from the TZ/TIMEZONE
      # env var", see Vdlarr.Boot.PreJobStartupTasks
      add :timezone, :string
    end
  end
end
