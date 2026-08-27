defmodule Pinchflat.Repo.Migrations.RemoveOnboardingFromSettings do
  use Ecto.Migration

  def change do
    alter table(:settings) do
      remove :onboarding, :boolean
    end
  end
end
