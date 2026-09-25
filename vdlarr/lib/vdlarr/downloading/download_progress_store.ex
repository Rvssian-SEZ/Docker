defmodule Vdlarr.Downloading.DownloadProgressStore do
  @moduledoc """
  Latest `Vdlarr.Downloading.DownloadState` per in-flight media item, held in ETS so a page
  opened (or refreshed) mid-download can show where it's at immediately instead of waiting
  for the next broadcast - which, during a long merge/post-processing pass, may be minutes
  away. The GenServer only owns the table; reads and writes go straight to ETS from the
  caller (each download is written by its own single worker process).
  """
  use GenServer

  alias Vdlarr.Downloading.DownloadState

  @table __MODULE__

  def start_link(_opts), do: GenServer.start_link(__MODULE__, nil, name: __MODULE__)

  @impl true
  def init(_) do
    :ets.new(@table, [:named_table, :public, :set, read_concurrency: true])

    {:ok, nil}
  end

  @doc """
  Applies `fun` to the item's current state (a fresh one if none) and stores the result.

  Returns DownloadState.t()
  """
  def update(media_item_id, fun) do
    new_state = fun.(get(media_item_id) || DownloadState.new())
    :ets.insert(@table, {media_item_id, new_state})

    new_state
  end

  def get(media_item_id) do
    case :ets.lookup(@table, media_item_id) do
      [{_, state}] -> state
      [] -> nil
    end
  end

  @doc """
  Every in-flight download's state, as a map of media_item_id => DownloadState.
  """
  def all, do: @table |> :ets.tab2list() |> Map.new()

  def clear do
    :ets.delete_all_objects(@table)

    :ok
  end

  def delete(media_item_id) do
    :ets.delete(@table, media_item_id)

    :ok
  end
end
