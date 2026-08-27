defmodule Pinchflat.Repo.Migrations.AddHiddenSourcesSupport do
  use Ecto.Migration

  def change do
    alter table(:sources) do
      add :hidden, :boolean, default: false, null: false
    end

    alter table(:settings) do
      add :show_hidden_sources_menu, :boolean, default: true, null: false
    end
  end
end
