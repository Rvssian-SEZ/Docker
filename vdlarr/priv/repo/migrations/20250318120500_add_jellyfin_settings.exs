defmodule Vdlarr.Repo.Migrations.AddJellyfinSettings do
  use Ecto.Migration

  def change do
    alter table(:settings) do
      add :jellyfin_url, :string
      add :jellyfin_api_key, :string
      add :jellyfin_path_prefix, :string
    end
  end
end
