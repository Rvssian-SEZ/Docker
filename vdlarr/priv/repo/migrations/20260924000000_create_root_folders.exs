defmodule Vdlarr.Repo.Migrations.CreateRootFolders do
  use Ecto.Migration

  def change do
    create table(:root_folders) do
      add :name, :string, null: false
      add :path, :string, null: false
      add :jellyfin_path, :string

      timestamps(type: :utc_datetime)
    end

    create unique_index(:root_folders, [:name])
    create unique_index(:root_folders, [:path])

    # nil = the default root (MEDIA_PATH), so existing profiles are unaffected
    alter table(:media_profiles) do
      add :root_folder_id, references(:root_folders, on_delete: :nilify_all)
    end

    create index(:media_profiles, [:root_folder_id])
  end
end
