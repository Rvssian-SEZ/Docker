defmodule VdlarrWeb.Layouts do
  use VdlarrWeb, :html

  embed_templates "layouts/*"
  embed_templates "layouts/partials/*"

  use Vdlarr.Media.MediaQuery

  alias Vdlarr.Repo
  alias Vdlarr.Profiles.MediaProfile

  @doc """
  Whether the given sidebar `href` should be shown as the active nav item for the current
  request path. Plain prefix-matching, except "/" (Dashboard) which only matches exactly, and
  "/sources" (Channels) which must not claim "/sources/hidden".
  """
  def nav_active?(request_path, "/"), do: request_path == "/"

  def nav_active?(request_path, "/sources") do
    String.starts_with?(request_path, "/sources") and not String.starts_with?(request_path, "/sources/hidden")
  end

  def nav_active?(request_path, href), do: String.starts_with?(request_path, href)

  @doc """
  Number of media items waiting to download, for the Wanted nav badge.
  """
  def wanted_count do
    MediaQuery.new()
    |> MediaQuery.require_assoc(:media_profile)
    |> where(^MediaQuery.pending())
    |> Repo.aggregate(:count)
  end

  def profile_badge_classes do
    ["bg-[#123e76] text-[#a9d0ff]", "bg-[#422066] text-[#d9b5ff]", "bg-[#064c37] text-[#79e8b9]"]
  end

  @doc """
  Every media profile with how many sources use it, for the sidebar's Media Profiles list.

  Returns [{id, name, source_count}]
  """
  def media_profile_source_counts do
    from(mp in MediaProfile,
      left_join: s in assoc(mp, :sources),
      where: is_nil(mp.marked_for_deletion_at),
      group_by: mp.id,
      order_by: [desc: count(s.id), asc: mp.name],
      select: {mp.id, mp.name, count(s.id)}
    )
    |> Repo.all()
  end

  @doc """
  Renders a sidebar menu item link

  ## Examples

      <.sidebar_link icon="hero-home" text="Home" href="/" />
  """
  attr :icon, :string, required: true
  attr :text, :string, required: true
  attr :href, :any, required: true
  attr :target, :any, default: "_self"
  attr :icon_class, :string, default: ""
  attr :active, :boolean, default: false
  attr :badge, :any, default: nil

  def sidebar_item(assigns) do
    ~H"""
    <li>
      <.sidebar_link
        icon={@icon}
        text={@text}
        href={@href}
        target={@target}
        icon_class={@icon_class}
        active={@active}
        badge={@badge}
      />
    </li>
    """
  end

  @doc """
  Renders a sidebar menu item with a submenu

  ## Examples

      <.sidebar_submenu icon="hero-home" text="Home" current_path="/">
        <:submenu icon="hero-home" text="Home" href="/" />
      </.sidebar_submenu>
  """

  attr :icon, :string, required: true
  attr :text, :string, required: true
  attr :current_path, :string, required: true

  slot :submenu do
    attr :icon, :string
    attr :text, :string
    attr :href, :any
    attr :target, :any
  end

  def sidebar_submenu(assigns) do
    initially_selected = Enum.any?(assigns[:submenu], &(&1[:href] == assigns[:current_path]))
    assigns = Map.put(assigns, :initially_selected, initially_selected)

    ~H"""
    <li class="text-bodydark1" x-data={"{ selected: #{@initially_selected} }"}>
      <span
        class={[
          "font-medium cursor-pointer",
          "group relative flex items-center justify-between rounded-sm px-4 py-2 duration-300 ease-in-out",
          "duration-300 ease-in-out",
          "hover:bg-meta-4"
        ]}
        x-on:click="selected = !selected"
      >
        <span class="flex items-center gap-2.5">
          <.icon name={@icon} /> {@text}
        </span>
        <span class="text-bodydark2">
          <.icon name="hero-chevron-down" x-bind:class="{ 'rotate-180': selected }" />
        </span>
      </span>

      <ul x-cloak x-show="selected">
        <li :for={menu <- @submenu} class="text-bodydark2">
          <.sidebar_link icon={menu[:icon]} text={menu[:text]} href={menu[:href]} target={menu[:target]} class="pl-10" />
        </li>
      </ul>
    </li>
    """
  end

  @doc """
  Renders a sidebar menu item link

  ## Examples

      <.sidebar_link icon="hero-home" text="Home" href="/" />
  """
  attr :icon, :string
  attr :text, :string, required: true
  attr :href, :any, required: true
  attr :target, :any, default: "_self"
  attr :class, :string, default: ""
  attr :icon_class, :string, default: ""
  attr :active, :boolean, default: false
  attr :badge, :any, default: nil

  def sidebar_link(assigns) do
    ~H"""
    <.link
      href={@href}
      target={@target}
      class={[
        "group relative flex items-center gap-4 rounded-xl px-4 py-3 text-[14px] transition",
        if(@active,
          do: "bg-m3-active text-[#c9e2ff]",
          else: "text-[#c4cfdf] hover:bg-[#111a25] hover:text-white"
        ),
        @class
      ]}
    >
      <%= if @icon && String.starts_with?(@icon, "hero-") do %>
        <.icon name={@icon} class={"#{@icon_class} #{if @active, do: "text-[#7eb7ff]", else: ""}"} />
      <% else %>
        <.material_icon :if={@icon} name={@icon} class={"#{@icon_class} #{if @active, do: "text-[#7eb7ff]", else: ""}"} />
      <% end %>
      <span class="flex-1">{@text}</span>
      <span
        :if={@badge not in [nil, 0]}
        class="grid h-6 min-w-6 place-items-center rounded-full bg-[#293645] px-2 text-xs text-[#edf1f7]"
      >
        {@badge}
      </span>
    </.link>
    """
  end
end
