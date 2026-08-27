defmodule Pinchflat.Repo.Migrations.AddIndexCronScheduleToSources do
  use Ecto.Migration

  def change do
    alter table(:sources) do
      add :index_cron_schedule, :string
    end
  end
end
