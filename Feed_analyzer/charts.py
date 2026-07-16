from typing import List, Dict, Any

def compile_chart_data(group_data: List[Dict[str, Any]], max_items: int = 15) -> Dict[str, Any]:
    """Converts a group-by SQL output into Chart.js compatible JSON format.
    
    Combines nested keys with a " > " separator for multi-level group-bys.
    Truncates at max_items to prevent charts from becoming cluttered.
    """
    labels = []
    data = []
    
    # Process up to max_items
    for item in group_data[:max_items]:
        keys = item.get("keys", [])
        count = item.get("count", 0)
        
        # Combine multi-level keys, e.g. ["US", "TX"] -> "US > TX"
        label = " > ".join(str(k) for k in keys) if keys else "Unknown"
        labels.append(label)
        data.append(count)
        
    # If there are items beyond the limit, compile them into an "Other" category
    other_count = sum(item.get("count", 0) for item in group_data[max_items:])
    if other_count > 0:
        labels.append("Other")
        data.append(other_count)
        
    return {
        "labels": labels,
        "datasets": [{
            "label": "Record Count",
            "data": data,
            "backgroundColor": [
                "rgba(99, 102, 241, 0.7)",   # Indigo
                "rgba(14, 165, 233, 0.7)",   # Sky
                "rgba(234, 179, 8, 0.7)",    # Yellow
                "rgba(239, 68, 68, 0.7)",     # Red
                "rgba(16, 185, 129, 0.7)",   # Emerald
                "rgba(168, 85, 247, 0.7)",   # Purple
                "rgba(249, 115, 22, 0.7)",   # Orange
                "rgba(236, 72, 153, 0.7)",   # Pink
                "rgba(20, 184, 166, 0.7)",   # Teal
                "rgba(107, 114, 128, 0.7)"   # Gray
            ][:len(labels)],
            "borderColor": [
                "rgba(99, 102, 241, 1)",
                "rgba(14, 165, 233, 1)",
                "rgba(234, 179, 8, 1)",
                "rgba(239, 68, 68, 1)",
                "rgba(16, 185, 129, 1)",
                "rgba(168, 85, 247, 1)",
                "rgba(249, 115, 22, 1)",
                "rgba(236, 72, 153, 1)",
                "rgba(20, 184, 166, 1)",
                "rgba(107, 114, 128, 1)"
            ][:len(labels)],
            "borderWidth": 1.5
        }]
    }
