#!/bin/bash
# Check Testudo scraper progress

echo "=== Testudo Scraper Progress ==="
echo ""

# Count scraped departments
SCRAPED=$(ls testudo_courses/*.json 2>/dev/null | wc -l | xargs)
TOTAL=195
PERCENT=$((SCRAPED * 100 / TOTAL))

echo "Departments scraped: $SCRAPED / $TOTAL ($PERCENT%)"
echo ""

# Check if process is running
if ps aux | grep "[s]crape_testudo" | grep -q .; then
    echo "Status: ✓ Running"
else
    echo "Status: ✗ Stopped"
fi
echo ""

# Show most recent 10 departments
echo "Most recently scraped (last 10):"
ls -lt testudo_courses/*.json 2>/dev/null | head -10 | awk '{print $9}' | xargs -I {} basename {} .json | tr '\n' ' '
echo ""
echo ""

# Check for errors in log
if [ -f testudo_scrape.log ]; then
    ERROR_COUNT=$(grep -i "error\|failed\|exception" testudo_scrape.log 2>/dev/null | wc -l | xargs)
    if [ "$ERROR_COUNT" -gt 0 ]; then
        echo "⚠️  Found $ERROR_COUNT potential errors in log"
        echo "Run: grep -i 'error\|failed' testudo_scrape.log"
    else
        echo "✓ No errors detected in log"
    fi
fi
