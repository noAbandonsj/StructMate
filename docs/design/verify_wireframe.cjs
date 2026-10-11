// Usage: node verify_wireframe.cjs <playwright-module> <browser-exe> <preview-html> <output-directory>
// Uses an existing browser only. Does not install or download dependencies.
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const assert = require('node:assert/strict');
const [modulePath, executablePath, previewPath, outputDir] = process.argv.slice(2);
if (!outputDir) throw new Error('Expected four arguments; see usage.');
const {chromium} = require(modulePath);

(async () => {
  fs.mkdirSync(outputDir, {recursive:true});
  const browser = await chromium.launch({headless:true, executablePath});
  try {
    const page = await browser.newPage({viewport:{width:1056,height:1100},colorScheme:'light'});
    const errors = [];
    page.on('pageerror',error=>errors.push(error.message));
    await page.goto(pathToFileURL(path.resolve(previewPath)).href);
    const f = page.frameLocator('iframe');
    await f.locator('#ds-page-title').waitFor();
    const checks=[];
    const check=(name)=>checks.push(name);
    const nav=async label=>{await f.locator('nav').getByRole('button',{name:label,exact:true}).click();assert.equal(await f.locator('#ds-page-title').textContent(),label);};
    assert.equal(await f.locator('#ds-page-title').textContent(),'学习对话');
    await page.screenshot({path:path.join(outputDir,'chat-desktop.png'),fullPage:true});
    await f.getByRole('button',{name:'查看依据 [1]',exact:true}).click();
    assert.equal(await f.locator('aside.ds-panel').isVisible(),false);
    await f.getByRole('button',{name:'查看依据 [1]',exact:true}).click();
    assert.equal(await f.locator('aside.ds-panel').isVisible(),true);
    check('citation panel toggles');
    await f.locator('#ds-mode').selectOption('guide');
    assert.equal(await f.getByText('先想一想：如果队头和队尾重合，你如何判断队列是空还是满？',{exact:true}).count(),1);
    await f.locator('#ds-mode').selectOption('explain');
    check('teaching mode changes');
    await f.getByRole('button',{name:'总结本次对话',exact:true}).click();
    assert.equal(await f.getByText('本次总结',{exact:true}).count(),1);
    check('conversation summary appears');
    await f.getByRole('button',{name:'练习这个知识点',exact:true}).click();
    await f.locator('input[name="ds-answer"][value="0"]').check();
    await f.getByRole('button',{name:'提交答案',exact:true}).click();
    assert.equal(await f.getByText('本题已收录到错题本',{exact:true}).count(),1);
    assert.equal(await f.getByRole('button',{name:'已提交',exact:true}).isDisabled(),true);
    check('incorrect attempt enters wrong-question flow and cannot submit twice');
    await nav('错题本');
    assert.equal(await f.getByText('错误 1 次 · 复习 0 次',{exact:true}).count(),1);
    await page.screenshot({path:path.join(outputDir,'wrong-desktop.png'),fullPage:true});
    await f.getByRole('button',{name:'重做这道题',exact:true}).click();
    await f.locator('input[name="ds-answer"][value="1"]').check();
    await f.getByRole('button',{name:'提交答案',exact:true}).click();
    assert.equal(await f.getByText('回答正确',{exact:true}).count(),1);
    await nav('错题本');
    assert.equal(await f.getByText('复习中',{exact:true}).count(),1);
    check('review preserves initial wrong attempt');
    await nav('学习报告');
    await f.getByRole('button',{name:'生成学习建议',exact:true}).click();
    const values=await f.locator('.ds-value').allTextContents();
    assert.deepEqual(values,['2 题','0%','1 次']);
    check('report separates first-attempt accuracy from review');
    await page.screenshot({path:path.join(outputDir,'report-desktop.png'),fullPage:true});
    await nav('我的知识库');
    await f.getByRole('button',{name:'模拟上传笔记',exact:true}).click();
    await f.getByText('已就绪 · 可检索',{exact:true}).waitFor();
    check('mock ingestion reaches ready state');
    await nav('学习对话');
    await f.locator('#ds-question').fill('有效容量是多少？');
    await f.getByRole('button',{name:'发送',exact:true}).click();
    assert.equal(await f.getByText('有效容量是多少？',{exact:true}).count(),1);
    check('chat input updates example question');
    for (const width of [1056,352]) {
      await page.setViewportSize({width,height:1200});
      for (const label of ['学习首页','我的知识库','学习对话','练习中心','错题本','学习报告']) {
        await nav(label);
        const overflow=await f.locator('#rag-study-wireframe').evaluate(el=>{
          const r=el.getBoundingClientRect();
          const offenders=[...el.querySelectorAll('*')].filter(x=>{
            const b=x.getBoundingClientRect();
            return b.width>0 && b.height>0 && (b.right>r.right+2 || b.left<r.left-2);
          }).map(x=>x.tagName+'.'+x.className);
          return {scroll:el.scrollWidth-el.clientWidth,offenders};
        });
        assert.equal(overflow.scroll<=2,true,`${width}/${label}: ${JSON.stringify(overflow)}`);
        assert.deepEqual(overflow.offenders,[],`${width}/${label}: overflow`);
      }
      check(`all six pages fit ${width-32}px content width`);
    }
    await nav('学习对话');
    await page.screenshot({path:path.join(outputDir,'chat-mobile.png'),fullPage:true});
    await page.setViewportSize({width:1056,height:1100});
    await page.emulateMedia({colorScheme:'dark'});
    await page.screenshot({path:path.join(outputDir,'chat-dark.png'),fullPage:true});
    assert.deepEqual(errors,[]);
    check('no JavaScript runtime errors');
    const result={checks_passed:checks.length,checks,scope:'local wireframe simulation; no API or model calls'};
    fs.writeFileSync(path.join(outputDir,'wireframe-checks.json'),JSON.stringify(result,null,2));
    console.log(JSON.stringify(result,null,2));
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
