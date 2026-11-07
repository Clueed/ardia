#import "ArdiaChromeWindowInternal.h"
#import "ArdiaRuntime.h"

#import <objc/runtime.h>

#include <initializer_list>

using namespace ardia_runtime;

namespace {

const void *kAgentWindowKey = &kAgentWindowKey;
constexpr NSWindowLevel kAgentLevel = -1000000;
constexpr CGFloat kAgentWidth = 1280;
constexpr CGFloat kAgentHeight = 800;
constexpr CGFloat kAgentGap = 200;
constexpr NSWindowCollectionBehavior kAgentBehavior =
    NSWindowCollectionBehaviorTransient | NSWindowCollectionBehaviorIgnoresCycle | NSWindowCollectionBehaviorFullScreenNone;

bool Agent(NSWindow *window) {
  return objc_getAssociatedObject(window, kAgentWindowKey) != nil;
}

NSHashTable<NSWindow *> *AgentWindows() {
  static NSHashTable *windows = [NSHashTable weakObjectsHashTable];
  return windows;
}

NSPoint OffScreenOrigin() {
  NSRect all = NSZeroRect;
  for (NSScreen *screen in NSScreen.screens) all = NSUnionRect(all, screen.frame);
  return NSMakePoint(NSMinX(all) - kAgentWidth - kAgentGap, NSMinY(all) - kAgentHeight - kAgentGap);
}

NSRect OffScreen(NSSize size) {
  const NSPoint origin = OffScreenOrigin();
  return NSMakeRect(origin.x, origin.y, size.width, size.height);
}

template <typename Signature>
Signature Original(IMP original) {
  return (Signature)original;
}

void GuardClass(Class cls) {
  static NSMutableSet<Class> *guarded = [NSMutableSet set];
  if ([guarded containsObject:cls]) return;
  [guarded addObject:cls];
  for (SEL selector : {@selector(canBecomeKeyWindow), @selector(canBecomeMainWindow)}) {
    ReplaceMethod(cls, selector, ^id(IMP original) {
      return ^BOOL(NSWindow *window) { return Agent(window) ? NO : Original<BOOL (*)(id, SEL)>(original)(window, selector); };
    });
  }
  for (SEL selector : {@selector(makeKeyWindow), @selector(makeMainWindow), @selector(becomeKeyWindow), @selector(becomeMainWindow)}) {
    ReplaceMethod(cls, selector, ^id(IMP original) {
      return ^(NSWindow *window) {
        if (!Agent(window)) Original<void (*)(id, SEL)>(original)(window, selector);
      };
    });
  }
  for (SEL selector : {@selector(makeKeyAndOrderFront:), @selector(orderFront:), @selector(toggleFullScreen:)}) {
    ReplaceMethod(cls, selector, ^id(IMP original) {
      return ^(NSWindow *window, id sender) {
        if (!Agent(window)) return Original<void (*)(id, SEL, id)>(original)(window, selector, sender);
        if (selector != @selector(toggleFullScreen:)) [window orderBack:nil];
      };
    });
  }
  ReplaceMethod(cls, @selector(orderFrontRegardless), ^id(IMP original) {
    return ^(NSWindow *window) {
      if (Agent(window)) return [window orderBack:nil];
      Original<void (*)(id, SEL)>(original)(window, @selector(orderFrontRegardless));
    };
  });
  ReplaceMethod(cls, @selector(orderWindow:relativeTo:), ^id(IMP original) {
    return ^(NSWindow *window, NSWindowOrderingMode place, NSInteger other) {
      const bool agent = Agent(window) && place == NSWindowAbove;
      Original<void (*)(id, SEL, NSWindowOrderingMode, NSInteger)>(original)(window, @selector(orderWindow:relativeTo:), agent ? NSWindowBelow : place,
                                                                              agent ? 0 : other);
    };
  });
  ReplaceMethod(cls, @selector(setLevel:), ^id(IMP original) {
    return ^(NSWindow *window, NSWindowLevel level) {
      Original<void (*)(id, SEL, NSWindowLevel)>(original)(window, @selector(setLevel:), Agent(window) ? kAgentLevel : level);
    };
  });
  ReplaceMethod(cls, @selector(setCollectionBehavior:), ^id(IMP original) {
    return ^(NSWindow *window, NSWindowCollectionBehavior behavior) {
      Original<void (*)(id, SEL, NSWindowCollectionBehavior)>(original)(window, @selector(setCollectionBehavior:), Agent(window) ? kAgentBehavior : behavior);
    };
  });
  ReplaceMethod(cls, @selector(constrainFrameRect:toScreen:), ^id(IMP original) {
    return ^NSRect(NSWindow *window, NSRect frame, NSScreen *screen) {
      if (Agent(window)) return frame;
      return Original<NSRect (*)(id, SEL, NSRect, NSScreen *)>(original)(window, @selector(constrainFrameRect:toScreen:), frame, screen);
    };
  });
  ReplaceMethod(cls, @selector(setFrame:display:), ^id(IMP original) {
    return ^(NSWindow *window, NSRect frame, BOOL display) {
      Original<void (*)(id, SEL, NSRect, BOOL)>(original)(window, @selector(setFrame:display:), Agent(window) ? OffScreen(frame.size) : frame, display);
    };
  });
}

void Place(NSWindow *window) {
  [window setFrame:OffScreen(NSMakeSize(kAgentWidth, kAgentHeight)) display:NO];
}

void KeepSeen(NSWindow *window) {
  if (![ardia_window::ActedOcclusion(window) isEqual:@YES]) ardia_window::ActOcclusion(window, @YES);
}

void WatchScreens() {
  static dispatch_once_t once;
  dispatch_once(&once, ^{
    [NSNotificationCenter.defaultCenter addObserverForName:NSApplicationDidChangeScreenParametersNotification
                                                    object:nil
                                                     queue:NSOperationQueue.mainQueue
                                                usingBlock:^(NSNotification *) {
                                                  for (NSWindow *window in AgentWindows().allObjects) Place(window);
                                                }];
    [NSNotificationCenter.defaultCenter addObserverForName:NSWindowDidChangeOcclusionStateNotification
                                                    object:nil
                                                     queue:nil
                                                usingBlock:^(NSNotification *note) {
                                                  NSWindow *window = note.object;
                                                  if ([window isKindOfClass:NSWindow.class] && Agent(window)) KeepSeen(window);
                                                }];
  });
}

}

namespace ardia_window {

BOOL IsAgentWindow(NSWindow *window) {
  return window && Agent(window);
}

}

@implementation ArdiaChromeWindowHost (Agent)

+ (void)keepAgentWindow:(NSWindow *)window {
  if (!window) return;
  GuardClass(object_getClass(window));
  objc_setAssociatedObject(window, kAgentWindowKey, @YES, OBJC_ASSOCIATION_RETAIN_NONATOMIC);
  [AgentWindows() addObject:window];
  WatchScreens();
  window.restorable = NO;
  window.excludedFromWindowsMenu = YES;
  window.hidesOnDeactivate = NO;
  window.animationBehavior = NSWindowAnimationBehaviorNone;
  window.alphaValue = 1;
  window.level = kAgentLevel;
  window.collectionBehavior = kAgentBehavior;
  Place(window);
  KeepSeen(window);
}

+ (BOOL)isAgentWindow:(NSWindow *)window {
  return ardia_window::IsAgentWindow(window);
}

@end
