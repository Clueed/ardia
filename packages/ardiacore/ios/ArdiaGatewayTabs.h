#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

@interface ArdiaGatewayTabs : NSObject
+ (NSArray<NSDictionary<NSString *, NSString *> *> *)hostedTabs NS_SWIFT_NAME(hostedTabs());
+ (void)targetOfTab:(NSString *)tabId
         completion:(void (^)(NSDictionary<NSString *, id> *_Nullable targetInfo))completion NS_SWIFT_NAME(target(ofTab:completion:));
@end

NS_ASSUME_NONNULL_END
