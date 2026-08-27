defmodule Pinchflat.Repo.Migrations.AddTimezoneToSettings do
  use Ecto.Migration

  def change do
    alter table(:settings) do
      # Deliberately no default - nil means "not yet seeded from the TZ/TIMEZONE
      # env var", see Pinchflat.Boot.PreJobStartupTasks
      add :timezone, :string
    end
  end
end
