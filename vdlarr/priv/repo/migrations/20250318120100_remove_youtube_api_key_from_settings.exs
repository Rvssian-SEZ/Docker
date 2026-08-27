defmodule Pinchflat.Repo.Migrations.RemoveYoutubeApiKeyFromSettings do
  use Ecto.Migration

  def change do
    alter table(:settings) do
      remove :youtube_api_key, :string
    end
  end
end
