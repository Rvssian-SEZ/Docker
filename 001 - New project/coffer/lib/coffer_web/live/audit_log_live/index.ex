defmodule CofferWeb.AuditLogLive.Index do
  use CofferWeb, :live_view

  alias Coffer.AuditLog
  alias Coffer.Authorization.Policy

  @impl true
  def mount(_params, _session, socket) do
    if Policy.can?(socket.assigns.current_user, :view, :audit_log) do
      {:ok,
       socket
       |> assign(:page_title, "Audit log")
       |> assign(:entries, AuditLog.list_entries())}
    else
      {:ok,
       socket
       |> put_flash(:error, "You're not authorized to view the audit log.")
       |> push_navigate(to: ~p"/")}
    end
  end

  @impl true
  def render(assigns) do
    ~H"""
    <div class="mx-auto max-w-5xl py-12">
      <.header>
        Audit log
        <:actions>
          <.link
            :if={Policy.can?(@current_user, :export, :audit_log)}
            href={~p"/admin/audit-log/export.csv"}
            class="btn btn-outline"
          >
            Export CSV
          </.link>
        </:actions>
      </.header>

      <.table id="audit-log" rows={@entries}>
        <:col :let={e} label="Time">{e.inserted_at}</:col>
        <:col :let={e} label="User">{e.user && e.user.name}</:col>
        <:col :let={e} label="Action">{e.action}</:col>
        <:col :let={e} label="Resource">{e.resource_type} #{e.resource_id}</:col>
      </.table>

      <.link href={~p"/"} class="link mt-6 inline-block">&larr; Back</.link>
    </div>
    """
  end
end
