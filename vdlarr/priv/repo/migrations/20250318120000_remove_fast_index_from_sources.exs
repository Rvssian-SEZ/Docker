defmodule Vdlarr.Repo.Migrations.RemoveFastIndexFromSources do
  use Ecto.Migration

  def change do
    alter table(:sources) do
      remove :fast_index, :boolean, null: false, default: false
    end
  end
end
