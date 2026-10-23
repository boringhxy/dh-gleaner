"""离线解析器测试共用的样例 HTML。

放一处是因为这些样例同时是「预期」的来源：`test_parsers.py` 断言字段抽取，
`test_agent.py` 拿同一份 HTML 走 capture 流程。以前两处各存一份逐字相同的副本，
改一处忘另一处时，两个文件会各自给出一个互相矛盾的「正确结构」。
"""

from __future__ import annotations

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
HTTP_CFG = {"userAgent": UA, "timeout": 30, "maxRetries": 3, "retryInterval": 10}

#: Journy3（《数字人文研究》dhr.ruc.edu.cn）经典皮肤
SAMPLE_JOURNY3 = """
<html><body>
<div>2026年 第6卷 第2期 刊出日期：2026-06-28</div>
<div class="wenzhanglanmu"><A name="理论探索"></A>理论探索</div>
<DIV id="art172" class="noselectrow">
  <a class="biaoti" href="/CN/Y2026/V6/I2/3">数字人文中的形式化偏向</a>
  <dd class="zuozhe">赵皓玥</dd>
  <dd class="kmnjq">2026, 6(2): 3-17.</dd>
  <a href="#1" onclick="lsdy1('PDF','172',1)">PDF</a> (9721KB)
  <div id="Abstract172" class="white_content zhaiyao">摘要文本</div>
</DIV>
</body></html>
"""

#: cnki_cbpt（《中国数字人文》）栏目列表
SAMPLE_CNKI = """
<html><body>
<h1>数字人文</h1>
<h1>数字史学</h1>
<ul class="column_contbox_zxlist">
  <li>
    <h3><a href="../WebPublication/paperDigest.aspx?paperID=uuid-123">历史数据可视化的路径</a></h3>
    <samp>周墨钦;王宏苏;</samp>
    <span>2025年04期  1-21页  <a href="../WebPublication/kbDownload.aspx?fn=SZRW202504001">下载</a> 3542K</span>
  </li>
</ul>
</body></html>
"""

#: magtech 经典皮肤（《图书馆论坛》）
SAMPLE_MAGTECH = """
<html><body>
<div>2025年, 第45卷, 第10期　刊出日期：2025-10-10</div>
<li class="noselectrow" id="art8925">
  <div class="j-title-1"><a href="/CN/Y2025/V45/I10/1">“十五五”时期图书馆的生成式AI战略</a></div>
  <div class="j-author">曹树金, 石佳, 张君宜</div>
  <div class="j-volumn">图书馆论坛. 2025, 45(10): 1-10.</div>
  <a class="j-pdf" href="javascript:;" onclick="lsdy1('PDF','8925');return false;">PDF全文</a>
  <div class="j-abstract">生成式AI摘要文本</div>
</li>
</body></html>
"""

#: generic_html（《中国数字人文》会议页）
SAMPLE_GENERIC = """
<html><body>
<h2>2025年目录</h2>
<ul>
  <li><a href="/article/a1">数字人文视野下的历史数据研究</a></li>
</ul>
</body></html>
"""

#: generic_html（DHCN《数字人文》某期清单页，WordPress 皮肤）
#: 站点菜单/页头/标签云/Read More 都挂在外壳里，真实条目只有 h2.entry-title 那两条。
SAMPLE_GENERIC_DHCN = """
<html><body>
<div class="side-menu"><ul class="sub-menu">
  <li class="menu-item"><a href="https://www.dhcn.cn/report">中国数字人文发展报告</a></li>
  <li class="menu-item"><a href="https://nav.dhcn.cn/#term-20">数字人文专业发展联盟</a></li>
</ul></div>
<div class="site-header-inside"><span><a href="https://www.dhcn.cn/">数字人文 | DHCN</a></span></div>
<h1 class="page-title">《数字人文》2025年第4期</h1>
<div class="cryout">
<article class="post"><div class="article-inner">
  <header class="entry-header"><h2 class="entry-title"><a href="https://mp.weixin.qq.com/s/AAA">迈向AI时代：数字人文基础设施的先锋之路 ——刘炜先生访谈录</a></h2></header>
  <div class="entry-after-image">
    <div class="entry-meta"><span class="tags"><a href="https://www.dhcn.cn/tag/t1">基础设施</a></span></div>
    <footer class="post-continue-container"><a href="https://mp.weixin.qq.com/s/AAA">Read More "迈向AI时代：数字人文基础设施的先锋之路"</a></footer>
  </div>
</div></article>
<article class="post"><div class="article-inner">
  <header class="entry-header"><h2 class="entry-title"><a href="https://mp.weixin.qq.com/s/BBB">基于改进YOLOv8的刺绣动态检测与分类研究</a></h2></header>
  <div class="entry-after-image">
    <footer class="post-continue-container"><a href="https://mp.weixin.qq.com/s/BBB">Read More "基于改进YOLOv8的刺绣动态检测与分类研究"</a></footer>
  </div>
</div></article>
</div>
</body></html>
"""
