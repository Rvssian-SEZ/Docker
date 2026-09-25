defmodule Vdlarr.RootFolders.RootFolder do
  @moduledoc """
  An extra top-level folder media can be saved into, alongside the default one (MEDIA_PATH) -
  eg: a second mounted share. Media profiles pick a root folder, and their output path
  template is relative to it.
  """

  use Ecto.Schema
  import Ecto.Changeset

  alias Vdlarr.Profiles.MediaProfile

  schema "root_folders" do
    field :name, :string
    field :path, :string
    # Where Jellyfin sees this same folder, if it mounts it at a different path
    field :jellyfin_path, :string

    has_many :media_profiles, MediaProfile

    timestamps(type: :utc_datetime)
  end

  @doc false
  def changeset(root_folder, attrs) do
    root_folder
    |> cast(attrs, [:name, :path, :jellyfin_path])
    |> update_change(:name, &String.trim/1)
    |> update_change(:path, &normalize_path/1)
    |> update_change(:jellyfin_path, &normalize_path/1)
    |> validate_required([:name, :path])
    |> validate_change(:path, fn :path, path ->
      if Path.type(path) == :absolute, do: [], else: [path: "must be an absolute path, eg: /downloads/archive"]
    end)
    |> unique_constraint(:name)
    |> unique_constraint(:path)
  end

  def normalize_path(nil), do: nil

  # Only absolute paths are expanded - Path.expand/1 would quietly turn a relative path into an
  # absolute one under the app's working directory, hiding the "must be absolute" error.
  def normalize_path(path) do
    trimmed = String.trim(path)

    cond do
      trimmed == "" -> nil
      trimmed == "/" -> "/"
      Path.type(trimmed) == :absolute -> trimmed |> Path.expand() |> String.trim_trailing("/")
      true -> String.trim_trailing(trimmed, "/")
    end
  end
end
