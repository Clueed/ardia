#import "ArdiaGatewayTabs.h"

#import "ArdiaInternal.h"
#import "ArdiaTabRegistry.h"
#import "ArdiaWebView.h"

namespace {
constexpr NSTimeInterval kTargetInfoTimeout = 2.0;
}

@implementation ArdiaGatewayTabs

+ (NSArray<NSDictionary<NSString *, NSString *> *> *)hostedTabs {
  NSMutableArray *tabs = [NSMutableArray array];
  for (ArdiaCoreTab *tab in [ArdiaTabRegistry hostedTabs]) {
    NSString *tabId = [ArdiaTabRegistry viewForTab:tab].transferKey;
    ArdiaCoreProfile *profile = tab.profile;
    if (!tabId.length || !profile || profile.offTheRecord || tab.closed) continue;
    [tabs addObject:@{@"tabId" : tabId, @"profile" : ardia_host::ProfileName(profile)}];
  }
  return tabs;
}

+ (void)targetOfTab:(NSString *)tabId completion:(void (^)(NSDictionary<NSString *, id> *))completion {
  ArdiaCoreTab *tab = ardia_host::TabWithAppTabId(tabId);
  if (!tab || tab.closed || tab.profile.offTheRecord) return completion(nil);
  [tab devToolsCall:@"Target.getTargetInfo"
              params:nil
             timeout:kTargetInfoTimeout
          completion:^(NSDictionary *result, NSString *error) {
            NSDictionary *info = [result[@"targetInfo"] isKindOfClass:NSDictionary.class] ? result[@"targetInfo"] : nil;
            completion(info);
          }];
}

@end
