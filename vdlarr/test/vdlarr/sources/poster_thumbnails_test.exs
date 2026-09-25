defmodule Vdlarr.Sources.PosterThumbnailsTest do
  use ExUnit.Case, async: false

  alias Vdlarr.Sources.PosterThumbnails

  @moduletag :tmp_dir

  defp make_image(dir, name, size) do
    path = Path.join(dir, name)
    {_, 0} = System.cmd("ffmpeg", ~w(-y -loglevel error -f lavfi -i color=c=blue:s=#{size} -frames:v 1) ++ [path])
    path
  end

  defp dimensions(path) do
    {out, 0} = System.cmd("ffprobe", ~w(-v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0) ++ [path])
    out |> String.trim() |> String.split(",") |> Enum.map(&String.to_integer/1)
  end

  describe "thumbnail_for/2" do
    test "makes a 400x400 thumbnail and reuses it on the next call", %{tmp_dir: dir} do
      if System.find_executable("ffmpeg") do
        poster = make_image(dir, "wide.jpg", "1280x720")

        assert {:ok, thumb} = PosterThumbnails.thumbnail_for(900_001, poster)
        assert dimensions(thumb) == [400, 400]

        %{mtime: first_mtime} = File.stat!(thumb, time: :posix)
        assert {:ok, ^thumb} = PosterThumbnails.thumbnail_for(900_001, poster)
        assert %{mtime: ^first_mtime} = File.stat!(thumb, time: :posix)
      end
    end

    test "a changed poster gets a fresh thumbnail and the stale one is removed", %{tmp_dir: dir} do
      if System.find_executable("ffmpeg") do
        poster = make_image(dir, "poster.jpg", "600x600")
        {:ok, old_thumb} = PosterThumbnails.thumbnail_for(900_002, poster)

        # Different size => different cache key
        make_image(dir, "poster.jpg", "900x600")
        {:ok, new_thumb} = PosterThumbnails.thumbnail_for(900_002, poster)

        assert new_thumb != old_thumb
        refute File.exists?(old_thumb)
        assert File.exists?(new_thumb)
      end
    end

    test "doesn't touch another source's thumbnails whose id shares a prefix", %{tmp_dir: dir} do
      if System.find_executable("ffmpeg") do
        a = make_image(dir, "a.jpg", "500x500")
        b = make_image(dir, "b.jpg", "700x500")
        {:ok, thumb_11} = PosterThumbnails.thumbnail_for(11, a)
        # Making source 1's thumbnail cleans up stale "1-*.jpg" files - which must not match "11-*.jpg"
        {:ok, _thumb_1} = PosterThumbnails.thumbnail_for(1, b)

        assert File.exists?(thumb_11)
      end
    end

    test "returns an error for a file that isn't an image or doesn't exist", %{tmp_dir: dir} do
      junk = Path.join(dir, "junk.jpg")
      File.write!(junk, "nope")

      assert {:error, _} = PosterThumbnails.thumbnail_for(900_003, junk)
      assert {:error, _} = PosterThumbnails.thumbnail_for(900_004, Path.join(dir, "missing.jpg"))
    end
  end
end
