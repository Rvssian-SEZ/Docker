defmodule Vdlarr.Repo.Migrations.AddYtDlpUpdatePolicyToSettings do
  use Ecto.Migration

  def change do
    alter table(:settings) do
      add :yt_dlp_update_policy, :string, default: "stable"
      add :yt_dlp_pinned_version, :string
      add :yt_dlp_nightly_baseline, :string
    end
  end
end
