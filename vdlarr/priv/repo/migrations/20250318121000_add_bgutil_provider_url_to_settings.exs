defmodule Vdlarr.Repo.Migrations.AddBgutilProviderUrlToSettings do
  use Ecto.Migration

  def change do
    alter table(:settings) do
      add :bgutil_provider_url, :string
    end
  end
end
