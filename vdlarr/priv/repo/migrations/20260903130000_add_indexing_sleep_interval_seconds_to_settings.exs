defmodule Vdlarr.Repo.Migrations.AddIndexingSleepIntervalSecondsToSettings do
  use Ecto.Migration

  def change do
    alter table(:settings) do
      add :indexing_sleep_interval_seconds, :integer, default: 5
    end
  end
end
