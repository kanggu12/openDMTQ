<?php
/*
 * The shop.* methods. Every player owns every song and most items from the start (content.php's catalog), and the
 * patched app removed the screens that would take money. What the shop still sells (the note skins nobody owns at first,
 * an item the owner took from a player, a pack of MAX POINT, a level unlock) is paid for with the currencies the server
 * keeps (player.php): MAX POINT (shop.buyFreeProduct) or Q (shop.buyProductByQPoint), the price the client's own tables
 * give it, nothing while the player's currency is unlimited. A purchase is kept either way: the item is the player's, and
 * PlayerPurchase notes it with what was paid. The game asks for the balance and the items right after (in the same
 * request), and shows them. Every shop call is signed (rpc.php refuses a batch with an unsigned one).
 */

require_once __DIR__ . '/content.php';
require_once __DIR__ . '/game.php';
require_once __DIR__ . '/player.php';

/*
 * shop.buyFreeProduct [guid, productId]: buy with MAX POINT, the game's free currency. The client sends here every
 * purchase whose price is in MAX POINT (a product with a MAX POINT cost: the first kind of a product's price) and sends the
 * others to buyProductByQPoint. A purchase the player cannot pay for is handled without a popup and changes nothing.
 */
function odq_shop_buy_free(array $p)
{
    if (!odq_shop_buy(odq_intval($p[0] ?? null), odq_intval($p[1] ?? null), null)) {
        return odq_error('SVC.05008', 'OpenDMTQ: this purchase is not possible on this server; nothing was bought');
    }
    // What this call answered before purchases were kept: the client reads nothing of it.
    return true;
}

/*
 * shop.buyProductByQPoint [guid, productId, extra]: buy with Q, the game's paid currency: every product without a MAX POINT
 * cost (a pack of MAX POINT, a partner, a level unlock). The client reads nothing of the reply, then asks for the balance
 * and the items; a purchase the player cannot pay for, or of a product the catalog does not have, is handled without a
 * popup and changes nothing.
 */
function odq_shop_buy_with_points(array $p)
{
    if (!odq_shop_buy(odq_intval($p[0] ?? null), odq_intval($p[1] ?? null), $p[2] ?? null)) {
        return odq_error('SVC.05008', 'OpenDMTQ: this purchase is not possible on this server; nothing was bought');
    }
    // The product id comes back as it was sent.
    return ['status' => true, 'product_id' => $p[1] ?? null, 'message' => 'SUCCESS'];
}

/*
 * One purchase, all of it or nothing: the price taken unless the player's currency is unlimited (or it is free), then what
 * the product gives: a pack of MAX POINT its amount (none while unlimited, which leaves the player's own balance as it
 * was), a level unlock the product it unlocks (extra, the product's id when it names none), anything else its item. Noted in PlayerPurchase with what was paid. The currency is the product's, as
 * the client decides it (MAX POINT when it has a MAX POINT cost, else Q), whichever of the two calls it came through: a
 * call sent to the other one takes the same price. False when nothing was bought: no such product, no account, a price
 * the player cannot pay, or a database that did not take it.
 */
function odq_shop_buy(int $guid, int $product_id, $extra): bool
{
    $product = odq_catalog()['products'][(string)$product_id] ?? null;
    if (!is_array($product) || $guid <= 0 || odq_account_known($guid) !== true) {
        return false;
    }
    // The price in the currency it is in: MAX POINT when the product has a MAX POINT cost, else Q (the client's rule).
    $point = max(0, (int)($product['point'] ?? 0));
    $cash = max(0, (int)($product['cash'] ?? 0));
    $currency = $point > 0 ? 'max' : ($cash > 0 ? 'q' : 'free');
    $price = $point > 0 ? $point : $cash;
    $db = odq_db();
    if (!@$db->exec('BEGIN IMMEDIATE')) {
        return false;
    }
    try {
        $state = odq_player_state($guid, $db);
        // What is taken: the price, unless their currency is unlimited; more than they have is no purchase.
        $paid = $state['unlimited'] ? 0 : $price;
        $has = $currency === 'max' ? $state['mpoint'] : ($currency === 'q' ? $state['qpoint'] : 0);
        if ($paid > $has) {
            @$db->exec('ROLLBACK');
            return false;
        }
        $kind = (string)($product['kind'] ?? '');
        // A partner, note skin or skin the player has already is no purchase (the shop says so itself, as it does
        // for a song they own); an add-on's uses may be bought again.
        if (in_array($kind, ['C', 'N', 'K'], true) && in_array((int)($product['item'] ?? 0), odq_owned_items($guid), true)) {
            @$db->exec('ROLLBACK');
            return false;
        }
        // A pack of MAX POINT gives its amount when it has a price: the free ones in the tables were the publisher's gifts,
        // which the shop never sells. Nothing while the player's currency is unlimited: nothing is paid then, and their own
        // balance stays as it was (player.php), so a pack never adds to it for free.
        $amount = $kind === 'M' && $price > 0 && !$state['unlimited'] ? max(0, (int)($product['amount'] ?? 0)) : 0;
        // The price out, and a pack's MAX POINT in, in one change.
        odq_state_add($db, $guid, ($currency === 'max' ? -$paid : 0) + $amount, $currency === 'q' ? -$paid : 0, 0);
        $item = (int)($product['item'] ?? 0);
        if ($kind === 'L') {
            // A level unlock: what it unlocks, as the shop names it (the product the player wanted before their level).
            $unlocked = is_numeric($extra) && (int)$extra > 0 ? (int)$extra : $product_id;
            $u = $db->prepare('INSERT OR IGNORE INTO PlayerUnlock (guid, product_id, at) VALUES (:g, :p, :now)');
            $u->bindValue(':g', $guid, SQLITE3_INTEGER);
            $u->bindValue(':p', $unlocked, SQLITE3_INTEGER);
            $u->bindValue(':now', time(), SQLITE3_INTEGER);
            if (!@$u->execute()) {
                throw new RuntimeException($db->lastErrorMsg());
            }
        } elseif ($kind !== 'M' && $item > 0) {
            // An item: the player's from now on, whether everyone else has it or not.
            odq_item_owned($db, $guid, $item, 'bought');
        }
        $w = $db->prepare('INSERT INTO PlayerPurchase (guid, product_id, item_id, currency, price, paid, at)
                           VALUES (:g, :p, :i, :c, :price, :paid, :now)');
        $w->bindValue(':g', $guid, SQLITE3_INTEGER);
        $w->bindValue(':p', $product_id, SQLITE3_INTEGER);
        $w->bindValue(':i', $item, SQLITE3_INTEGER);
        $w->bindValue(':c', $currency, SQLITE3_TEXT);
        $w->bindValue(':price', $price, SQLITE3_INTEGER);
        $w->bindValue(':paid', $paid, SQLITE3_INTEGER);
        $w->bindValue(':now', time(), SQLITE3_INTEGER);
        if (!@$w->execute() || !@$db->exec('COMMIT')) {
            throw new RuntimeException($db->lastErrorMsg());
        }
        return true;
    } catch (Throwable $e) {
        @$db->exec('ROLLBACK');
        error_log('opendmtq: shop: ' . $e->getMessage());
        return false;
    }
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
 * shop.getOwnItemList [guid]: every item the player owns (player.php's odq_owned_items()): the partners, skins, note skins,
 * MAX POINT packs and level unlocks of the client's tables that everyone has (catalog.json), but those the owner took from
 * them, and what they bought or were given; each with plenty of uses.
 */
function odq_shop_own_items(array $p)
{
    $items = [];
    foreach (odq_owned_items(odq_intval($p[0] ?? null)) as $id) {
        $items[] = ['item_id' => (int)$id, 'own_count' => 99, 'repeat_count' => 999, 'using_yn' => 'Y',
                    'reg_date' => '20170709025007', 'end_date' => ''];
    }
    return $items;
}

/*
 * shop.getUnlockedProductList [guid]: the products the player unlocked one by one with a level unlock (an item their level
 * did not reach yet, which the shop then sells them), as numbers: the list the client keeps them in.
 */
function odq_shop_unlocked(array $p)
{
    $ids = [];
    $q = @odq_db()->prepare('SELECT product_id FROM PlayerUnlock WHERE guid = :g ORDER BY product_id');
    if ($q) {
        $q->bindValue(':g', odq_intval($p[0] ?? null), SQLITE3_INTEGER);
        $r = @$q->execute();
        while ($r && ($row = $r->fetchArray(SQLITE3_NUM))) {
            $ids[] = (int)$row[0];
        }
    }
    return $ids;
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
