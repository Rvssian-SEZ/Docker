defmodule Vdlarr.Repo.Migrations.RemoveProEnabledFromSettings do
  use Ecto.Migration

  def change do
    alter table(:settings) do
      remove :pro_enabled, :boolean
    end
  end
end
