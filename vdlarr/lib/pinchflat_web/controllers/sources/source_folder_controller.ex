defmodule PinchflatWeb.Sources.SourceFolderController do
  use PinchflatWeb, :controller

  alias Pinchflat.Utils.FilesystemUtils

  @doc """
  Lists existing top-level folders under the media directory, for the source
  form's folder picker.
  """
  def index(conn, _params) do
    json(conn, %{folders: FilesystemUtils.list_media_subdirectories()})
  end
end
