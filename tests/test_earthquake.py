from __future__ import annotations

import unittest
from unittest.mock import patch

from god_bot.earthquake import EarthquakeError, latest_earthquake

FEED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>噴火に関する火山観測報</title>
    <link href="https://example.test/volcano.xml"/>
  </entry>
  <entry>
    <title>震源・震度に関する情報</title>
    <link href="https://example.test/earthquake.xml"/>
  </entry>
</feed>
""".encode("utf-8")

REPORT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Report xmlns:jmx_eb="http://xml.kishou.go.jp/jmaxml1/elementBasis1/">
  <Head>
    <ReportDateTime>2026-07-27T14:00:00+09:00</ReportDateTime>
  </Head>
  <Body>
    <Earthquake>
      <OriginTime>2026-07-27T13:56:00+09:00</OriginTime>
      <Hypocenter>
        <Area>
          <Name>遠州灘</Name>
          <jmx_eb:Coordinate description="北緯34.5度 東経137.8度 深さ20km">+34.5+137.8-20000/</jmx_eb:Coordinate>
        </Area>
      </Hypocenter>
      <jmx_eb:Magnitude description="Ｍ5.2">5.2</jmx_eb:Magnitude>
    </Earthquake>
    <Intensity>
      <Observation>
        <MaxInt>5-</MaxInt>
        <Pref><Name>静岡県</Name><MaxInt>5-</MaxInt></Pref>
        <Pref><Name>愛知県</Name><MaxInt>4</MaxInt></Pref>
      </Observation>
    </Intensity>
    <Comments>
      <ForecastComment><Text>この地震による津波の心配はありません。</Text></ForecastComment>
    </Comments>
  </Body>
</Report>
""".encode("utf-8")


class EarthquakeTests(unittest.TestCase):
    @patch("god_bot.earthquake._fetch_xml")
    def test_formats_latest_earthquake_from_jma_xml(self, fetch_xml) -> None:
        fetch_xml.side_effect = [FEED_XML, REPORT_XML]
        result = latest_earthquake()
        self.assertIn("発生: 2026/07/27 13:56", result)
        self.assertIn("震源: 遠州灘", result)
        self.assertIn("規模: Ｍ5.2", result)
        self.assertIn("最大震度: 5弱", result)
        self.assertIn("最大震度の地域: 静岡県", result)
        self.assertIn("津波の心配はありません", result)
        fetch_xml.assert_any_call("https://example.test/earthquake.xml")

    @patch("god_bot.earthquake._fetch_xml")
    def test_reports_when_feed_has_no_earthquake(self, fetch_xml) -> None:
        fetch_xml.return_value = """<feed xmlns="http://www.w3.org/2005/Atom">
        <entry><title>噴火警報・予報</title><link href="x"/></entry>
        </feed>""".encode("utf-8")
        with self.assertRaises(EarthquakeError):
            latest_earthquake()


if __name__ == "__main__":
    unittest.main()
