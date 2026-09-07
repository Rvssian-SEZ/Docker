defmodule VdlarrWeb.Sources.SourceLive.SourceEnableToggle do
  use VdlarrWeb, :live_component

  alias Vdlarr.Sources
  alias Vdlarr.Sources.Source

  def render(assigns) do
    ~H"""
    <div>
      <.form :let={f} for={@form} phx-change="update" phx-target={@myself} class="enabled_toggle_form">
        <.input id={"source_#{@source_id}_enabled_input"} field={f[:enabled]} type="toggle" />
      </.form>
    </div>
    """
  end

  def update(assigns, socket) do
    initial_data = %{
      source_id: assigns.source.id,
      form: Sources.change_source(%Source{}, assigns.source)
    }

    socket
    |> assign(initial_data)
    |> then(&{:ok, &1})
  end

  def handle_event("update", %{"source" => source_params}, %{assigns: assigns} = socket) do
    source = Sources.get_source!(assigns.source_id)
    Sources.update_source_from_params(source, source_params)

    {:noreply, socket}
  end
end
