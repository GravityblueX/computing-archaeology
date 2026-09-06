from dataclasses import dataclass
import random


@dataclass(order=True)
class Card:
    key: int
    payload: str


def _require_unique_master_keys(master):
    seen = set()
    for card in master:
        if card.key in seen:
            raise ValueError("master keys must be unique")
        seen.add(card.key)


def linear_lookup(master, transactions):
    _require_unique_master_keys(master)
    comparisons = 0
    matches = []
    for tx in transactions:
        for card in master:
            comparisons += 1
            if card.key == tx.key:
                matches.append((card, tx))
                break
    return comparisons, matches


def merge_join(master, transactions):
    """Reconcile transactions against a unique-key master stream."""
    _require_unique_master_keys(master)
    a = sorted(master)
    b = sorted(transactions)
    i = j = comparisons = 0
    matches = []
    only_a = []
    only_b = []
    master_matched = False

    while i < len(a) and j < len(b):
        comparisons += 1
        if a[i].key == b[j].key:
            matches.append((a[i], b[j]))
            j += 1
            master_matched = True
        elif a[i].key < b[j].key:
            if not master_matched:
                only_a.append(a[i])
            i += 1
            master_matched = False
        else:
            only_b.append(b[j])
            j += 1

    if master_matched:
        i += 1
    only_a.extend(a[i:])
    only_b.extend(b[j:])
    return comparisons, matches, only_a, only_b


def main():
    random.seed(1937)
    master = [Card(k, f"master-{k:03d}") for k in range(1, 101)]
    tx_keys = random.sample(range(1, 121), 30)
    transactions = [Card(k, f"tx-{k:03d}") for k in tx_keys]

    random.shuffle(master)
    random.shuffle(transactions)

    linear_comparisons, linear_matches = linear_lookup(master, transactions)
    merge_comparisons, merge_matches, only_a, only_b = merge_join(master, transactions)

    print("Punched-card sort/merge thought experiment")
    print(f"master cards:       {len(master)}")
    print(f"transaction cards:  {len(transactions)}")
    print(f"linear comparisons: {linear_comparisons}")
    print(f"merge comparisons:  {merge_comparisons}")
    print(f"matches:            {len(merge_matches)}")
    print(f"master-only:        {len(only_a)}")
    print(f"transaction-only:   {len(only_b)}")
    print()
    print("The sort cost is deliberately not modeled as IBM machine timing.")
    print("The point is that once streams are ordered, reconciliation becomes local.")


if __name__ == "__main__":
    main()
