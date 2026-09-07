defmodule Vdlarr.Repo.Migrations.AddCustomPosterFilepathToSources do
  use Ecto.Migration

  def change do
    alter table(:sources) do
      add :custom_poster_filepath, :string
    end
  end
end
