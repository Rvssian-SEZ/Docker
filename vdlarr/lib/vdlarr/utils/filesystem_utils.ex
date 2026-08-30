defmodule Vdlarr.Utils.FilesystemUtils do
  @moduledoc """
  Utility methods for working with the filesystem
  """
  alias Vdlarr.Media
  alias Vdlarr.Utils.StringUtils

  @doc """
  Checks if a file exists and has non-whitespace contents.

  Returns boolean()
  """
  def exists_and_nonempty?(filepath) do
    case File.read(filepath) do
      {:ok, contents} ->
        String.trim(contents) != ""

      _ ->
        false
    end
  end

  @doc """
  Checks if two filepaths reference the same file.

  Useful if you have a relative and absolute filepath and want to be sure they're the same file.
  Also works with symlinks.

  Returns boolean()
  """
  def filepaths_reference_same_file?(filepath_1, filepath_2) do
    {:ok, stat_1} = File.stat(filepath_1)
    {:ok, stat_2} = File.stat(filepath_2)

    identifier_1 = "#{stat_1.major_device}:#{stat_1.minor_device}:#{stat_1.inode}"
    identifier_2 = "#{stat_2.major_device}:#{stat_2.minor_device}:#{stat_2.inode}"

    identifier_1 == identifier_2
  end

  @doc """
  Generates a temporary file and returns its path. The file is empty and has the given type.
  Generates all the directories in the path if they don't exist.

  Returns binary()
  """
  def generate_metadata_tmpfile(type) do
    filename = StringUtils.random_string(64)
    # This "namespacing" is more to help with development since things get
    # weird in my editor when there are thousands of files in a single directory
    first_two = String.slice(filename, 0..1)
    second_two = String.slice(filename, 2..3)
    tmpfile_directory = Application.get_env(:vdlarr, :tmpfile_directory)

    filepath =
      Path.join([
        tmpfile_directory,
        first_two,
        second_two,
        "#{filename}.#{type}"
      ])

    :ok = write_p!(filepath, "")

    filepath
  end

  @doc """
  Writes content to a file, creating directories as needed.
  Takes the same args as File.write/3.

  Returns :ok | {:error, any()}
  """
  def write_p(file, content, modes \\ []) do
    dirname = Path.dirname(file)

    case File.mkdir_p(dirname) do
      :ok -> File.write(file, content, modes)
      err -> err
    end
  end

  @doc """
  Writes content to a file, creating directories as needed.
  Takes the same args as File.write!/3.

  Returns :ok | raises on error
  """
  def write_p!(filepath, content, modes \\ []) do
    :ok = write_p(filepath, content, modes)
  end

  @doc """
  Copies a file from source to destination, creating directories as needed.

  Returns :ok | raises on error
  """
  def cp_p!(source, destination) do
    destination
    |> Path.dirname()
    |> File.mkdir_p!()

    File.cp!(source, destination)
  end

  @doc """
  Lists the names of top-level subdirectories under the app's configured media
  directory, for the source form's folder picker. Deliberately one level deep -
  output templates only ever need to name the top-level "channel" folder, not
  browse nested date/title subfolders.

  Returns [] (rather than raising) if the directory doesn't exist or can't be
  read, since this is a UX nicety and shouldn't ever break a page.

  Returns [binary()]
  """
  def list_media_subdirectories do
    base_directory = Application.get_env(:vdlarr, :media_directory)

    case File.ls(base_directory) do
      {:ok, entries} ->
        entries
        |> Enum.reject(&String.starts_with?(&1, "."))
        |> Enum.filter(&File.dir?(Path.join(base_directory, &1)))
        |> Enum.sort()

      {:error, _reason} ->
        []
    end
  end

  @doc """
  Fetches the file size of a media item and saves it to the database.

  Returns {:ok, media_item} | {:error, any()}
  """
  def compute_and_save_media_filesize(media_item) do
    case File.stat(media_item.media_filepath) do
      {:ok, %{size: size}} ->
        Media.update_media_item(media_item, %{media_size_bytes: size})

      err ->
        err
    end
  end

  @doc """
  Deletes a file and removes any empty directories in the path.
  Does NOT remove any directories that are not empty.

  Returns :ok | {:error, any()}
  """
  def delete_file_and_remove_empty_directories(filepath) do
    case File.rm(filepath) do
      :ok ->
        filepath
        |> Path.dirname()
        |> recursively_delete_empty_directories()

      err ->
        err
    end
  end

  defp recursively_delete_empty_directories(directory) do
    case File.rmdir(directory) do
      :ok ->
        directory
        |> Path.dirname()
        |> recursively_delete_empty_directories()

      err ->
        err
    end

    :ok
  end
end
