<?php
/*
 * The shop.* methods. Nothing is sold on this server: every player owns every song and item from the start, so
 * the shop's answers say "owned" and "bought" without keeping anything. The patched app removed the screens that
 * would take money. Every shop call is signed (rpc.php refuses a batch with an unsigned one).
 */

require_once __DIR__ . '/content.php';
require_once __DIR__ . '/game.php';

/* shop.buyFreeProduct [guid, productId]: take a free product. Already owned. */
function odq_shop_buy_free(array $p)
{
    return true;
}

/* shop.buyProductByQPoint [guid, productId, extra]: buy with Q points. Done; the product id comes back as it was sent. */
function odq_shop_buy_with_points(array $p)
{
    return ['status' => true, 'product_id' => $p[1] ?? null, 'message' => 'SUCCESS'];
}

/*
 * shop.getPackageInfoByGuid [guid]: the song packages on sale and those bought. None: every song is owned anyway,
 * and the patched app has no package screen.
 */
function odq_shop_packages(array $p)
{
    return ['packageInfo' => [], 'packageInfoCount' => 0, 'purchasedPackageInfo' => [], 'purchasedPackageInfoCount' => 0,
            'packageItemList' => []];
}

/*
 * shop.getProductForUnlock [guid, productId]: the product that opens the next level band, for the unlock screen.
 * From the client's own product tables (catalog.json); without them an empty product of the same shape.
 */
function odq_shop_unlock_product(array $p)
{
    $product = odq_catalog()['unlock_product'];
    if (is_array($product)) {
        return $product;
    }
    return ['product_id' => 80002, 'platform_product_id' => 0, 'store_product_id' => '', 'product_type' => 'I',
            'cost_game_point' => 0, 'cost_game_cash' => 0, 'item_id' => 80002, 'item_name' => '', 'img_url_1' => '',
            'img_url_2' => '', 'summary' => '', 'description' => '', 'repeat_count' => 0, 'item_type' => 'L',
            'limit_minute' => 0, 'status' => 'N', 'buy_level' => 0, 'buy_limit_count' => 0, 'buy_limit_type' => '',
            'reg_date' => '', 'sale_start_date' => '', 'sale_end_date' => '', 'display_order' => 0];
}

/*
 * shop.getOwnItemList [guid]: every item the player owns: all partners, skins, note skins, MAX POINT packs and
 * level unlocks of the client's tables (catalog.json), each with plenty of uses.
 */
function odq_shop_own_items(array $p)
{
    $items = [];
    foreach (odq_catalog()['items'] as $id) {
        $items[] = ['item_id' => (int)$id, 'own_count' => 99, 'repeat_count' => 999, 'using_yn' => 'Y',
                    'reg_date' => '20170709025007', 'end_date' => ''];
    }
    return $items;
}

/* shop.getUnlockedProductList [guid]: products the player unlocked one by one. None needed: everything is owned. */
function odq_shop_unlocked(array $p)
{
    return [];
}

/*
 * shop.upgradeInGameItem [guid, itemType, itemLevel]: raise an in-game item's level. Every item is at its highest
 * level already (game.getUserAsset), so the client has nothing to raise; the reply has neither result nor error.
 */
function odq_shop_upgrade_item(array $p)
{
    return new OdqReply(null, null);
}

/*
 * shop.useCoupon [guid, code]: this server has no coupons, so every code is invalid. With error_Invalid true the
 * game shows its own "Invalid Coupon Code" popup. The capital I in error_Invalid is the client's.
 */
function odq_shop_use_coupon(array $p)
{
    return [
        // Nothing was given.
        'is_rewarded' => false,
        'reward_type' => '',
        'reward_value' => 0,
        // Only one of the three errors may be set; the client checks them in this order.
        'error_Invalid' => true,
        'error_limited' => false,
        'error_expired' => false,
    ];
}
