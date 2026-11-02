import { memo } from "react";
import { Animated, Pressable, ScrollView, View } from "react-native";
import { Badge, ContextMenuArea, Dot, ink, space, Symbol, Text, useHover, useTheme, WindowDragRegion, withAlpha } from "../ui";
import { layout } from "../ui/theme";
import { ThemeScope } from "../window/ThemeScope";
import { PageProfileContext, useProfile, useWindowId } from "../../state/browser/hooks";
import { AGENTS_PAGE } from "../../state/browser/agents";
import { useAgentFolderCollapsed, useAgentProfileIds, useAgentTabIds } from "../../state/profiles/hooks";
import { openAgentFolderMenu, toggleAgentFolder } from "../../state/profiles/agents";
import { useAgentConnected } from "../../state/app/cliConnect";
import { openSidebarMenu } from "../../state/sidebar/menus";
import { dismissHover } from "../../state/sidebar/hover";
import { registerRow } from "../../state/sidebar/sidebarUi";
import { usePageStyle } from "../../state/windows/profilePager";
import { DragScope } from "./DragProvider";
import { Fold, useFold, type FoldEntry } from "./Fold";
import { GROUP_BORDER, GROUP_HEADER_RADIUS, LIVE_FOLDER_PAD, GROUP_RADIUS } from "./geometry";
import { NoteRow } from "./LiveFolderRows";
import { listTopInset } from "./pageLayout";
import { useAddressBarInSidebar } from "../../state/windows/layout";
import { TabRow } from "./TabRow";
import { TAB_ROW, useSidebarTokens } from "./tokens";
import { SidebarRowLabel, SidebarRowSurface } from "./SidebarRow";

const EMPTY_LINE = "Agents you let use Ardia show up here.";
const CONNECTED_DOT = 7;

type AgentsPageProps = { slot: number; width: number; current: boolean; resting: boolean };

export const AgentsPage = memo(function AgentsPage({ slot, width, current, resting }: AgentsPageProps) {
  const windowId = useWindowId();
  const pageStyle = usePageStyle(windowId, slot, width);
  const agents = useAgentProfileIds();
  const topInset = listTopInset(useAddressBarInSidebar());
  return (
    <Animated.View
      pointerEvents={current ? "auto" : "none"}
      accessibilityLabel="Agents"
      style={{ position: "absolute", top: 0, bottom: 0, left: 0, width, display: resting ? "none" : "flex", ...pageStyle }}
    >
      <PageProfileContext.Provider value={AGENTS_PAGE}>
        <ThemeScope>
          <DragScope enabled={false}>
            <ScrollView
              style={{ flex: 1 }}
              showsVerticalScrollIndicator={false}
              contentContainerStyle={{ flexGrow: 1, width, paddingHorizontal: layout.sidebarInset, paddingTop: topInset, gap: layout.rowGap }}
            >
              {agents.length ? agents.map((id) => <AgentFolder key={id} profileId={id} windowId={windowId} />) : <EmptyLine />}
              <ContextMenuArea style={{ flexGrow: 1, minHeight: 24 }} onContextMenu={() => void openSidebarMenu(windowId)}>
                <WindowDragRegion style={{ flex: 1 }} titleBarDoubleClick={false} />
              </ContextMenuArea>
            </ScrollView>
          </DragScope>
        </ThemeScope>
      </PageProfileContext.Provider>
    </Animated.View>
  );
});

function EmptyLine() {
  return (
    <View style={EMPTY}>
      <Text size="small" tone="textSecondary">
        {EMPTY_LINE}
      </Text>
    </View>
  );
}

const AgentFolder = memo(function AgentFolder({ profileId, windowId }: { profileId: string; windowId: string }) {
  const tokens = useSidebarTokens();
  const tabIds = useAgentTabIds(windowId, profileId);
  const collapsed = useAgentFolderCollapsed(profileId);
  const fold = useFold(collapsed);
  const entries: FoldEntry[] = tabIds.length
    ? tabIds.map((id) => ({ key: id, node: <TabRow tabId={id} /> }))
    : [{ key: "none", node: <NoteRow text="No tabs open" /> }];
  return (
    <View
      style={{ borderRadius: GROUP_RADIUS, backgroundColor: tokens.groupFill, borderWidth: GROUP_BORDER, borderColor: tokens.groupStroke, paddingHorizontal: LIVE_FOLDER_PAD }}
    >
      <View style={{ marginHorizontal: -LIVE_FOLDER_PAD }}>
        <AgentFolderHeader profileId={profileId} windowId={windowId} open={fold.open} count={tabIds.length} collapsed={collapsed} />
      </View>
      <Fold fold={fold} collapsed={collapsed} entries={entries} padBottom={LIVE_FOLDER_PAD} />
    </View>
  );
});

function AgentFolderHeader({ profileId, windowId, open, count, collapsed }: { profileId: string; windowId: string; open: Animated.Value; count: number; collapsed: boolean }) {
  const theme = useTheme();
  const tokens = useSidebarTokens();
  const name = useProfile(profileId, (p) => p?.name ?? "");
  const connected = useAgentConnected(profileId);
  const { hovered, hoverProps } = useHover();
  return (
    <View ref={(v) => registerRow(windowId, `agentfolder|${profileId}`, v)} {...hoverProps}>
      <ContextMenuArea
        onContextMenu={() => {
          dismissHover();
          void openAgentFolderMenu(profileId, windowId);
        }}
      >
        <Pressable accessibilityRole="button" accessibilityLabel={name} accessibilityState={{ expanded: !collapsed }} onPress={() => toggleAgentFolder(profileId)}>
          {({ pressed }) => (
            <SidebarRowSurface
              fill={pressed ? theme.tabPressed : hovered ? tokens.groupHeaderHover : ink.clear}
              cornerRadius={GROUP_HEADER_RADIUS}
              padLeft={TAB_ROW.contentLeft + LIVE_FOLDER_PAD}
              padRight={TAB_ROW.trailing + LIVE_FOLDER_PAD}
            >
              <Symbol name="terminal" size={11} weight="medium" color={tokens.groupTitle} style={ICON} />
              <SidebarRowLabel text={name} weight="medium" color={tokens.groupTitle} />
              <View style={TRAILING}>
                {connected ? (
                  <View accessibilityLabel="Connected">
                    <Dot size={CONNECTED_DOT} color={theme.success} />
                  </View>
                ) : null}
                {collapsed && count ? <Badge text={count} size="m" /> : null}
                <Animated.View style={[CHEVRON, { transform: [{ rotate: open.interpolate({ inputRange: [0, 1], outputRange: ["-90deg", "0deg"] }) }] }]}>
                  <Symbol name="chevron.down" size={9} weight="semibold" color={withAlpha(tokens.groupTitle, 0.5)} style={CHEVRON} />
                </Animated.View>
              </View>
            </SidebarRowSurface>
          )}
        </Pressable>
      </ContextMenuArea>
    </View>
  );
}

const ICON = { width: 16, height: 16 } as const;
const CHEVRON = { width: 10, height: 10 } as const;
const TRAILING = { flexDirection: "row", alignItems: "center", gap: space.s } as const;
const EMPTY = { paddingHorizontal: TAB_ROW.contentLeft, minHeight: layout.rowHeight, justifyContent: "center" } as const;
